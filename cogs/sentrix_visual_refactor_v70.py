"""SentriX V70 — refonte visuelle Discord unifiée.

Cette couche est volontairement petite côté architecture : la source de vérité reste
``utils.embeds``. V70 ne réécrit pas la logique métier des commandes ; elle branche la
fabrique centrale sur les anciens chemins d'envoi, remplace l'aide historique et remplace
les nombreux renderers de logs par un seul embed Discord standard.

Objectifs :
- conserver les commandes + et / utiles ;
- aucun emoji décoratif dans l'interface ;
- +help / /help en embed compact, paginé et recherchable ;
- une seule couleur et un seul footer ;
- bannière horizontale sur les panneaux importants ;
- logs en embeds standards avec fields inline intelligents ;
- aucune espace invisible/padding artificiel ;
- déduplication des logs conservée ;
- contenus utilisateurs conservés tels quels.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from datetime import datetime, timezone
import logging
import re
import time
import types
from typing import Any

import discord
from discord.ext import commands

from utils import embeds as sx_embeds
from utils import log_service, premium_style

logger = logging.getLogger("bot.sentrix-visual-v70")
_INSTALLED = False
_HELP_ALL = "__sentrix_v70_all__"
_LOG_TTL = 14.0
_LOG_RECENT: dict[str, float] = {}


# ---------------------------------------------------------------------------
# Style central — aucune donnée utilisateur n'est nettoyée.
# ---------------------------------------------------------------------------

def _clean_label(value: Any, limit: int = 90, fallback: str = "") -> str:
    return sx_embeds.clean_ui_text(value, limit, fallback)


def _command_category(command: commands.Command | None) -> str:
    if command is None:
        return "Autres"
    try:
        from . import help_complete
        category = help_complete._category_for(command)
        return _clean_label(category.name, 70, "Autres") or "Autres"
    except Exception:
        cog = getattr(command, "cog", None)
        return _clean_label(getattr(cog, "qualified_name", "Autres"), 70, "Autres") or "Autres"


def _category_key(command: commands.Command | None) -> str:
    if command is None:
        return "other"
    try:
        from . import help_complete
        return str(help_complete._category_for(command).key)
    except Exception:
        cog = getattr(command, "cog", None)
        return str(getattr(cog, "qualified_name", "other") or "other").casefold()


def _is_staff_command(command: commands.Command | None) -> bool:
    if command is None:
        return False
    try:
        from . import utility
        return bool(utility.is_staff_command(command))
    except Exception:
        return False


def _short_title(embed: discord.Embed) -> str:
    raw = str(embed.title or "Information")
    raw = re.sub(r"^\s*SentriX\s*[•/|-]\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"^\s*Journal\s+", "", raw, flags=re.IGNORECASE)
    return _clean_label(raw, 90, "Information") or "Information"


def _style_embed(
    embed: discord.Embed,
    *,
    command: commands.Command | None = None,
    guild: discord.Guild | None = None,
    category: str | None = None,
    log_type: str | None = None,
    **_kwargs,
) -> discord.Embed:
    """Dernier style appliqué aux anciens embeds sans modifier leurs valeurs métier."""
    if not isinstance(embed, discord.Embed):
        return embed

    embed.title = _short_title(embed)
    embed.colour = discord.Colour(sx_embeds.SENTRIX_COLOR)

    # Une ancienne couche peut avoir répété « SentriX • ... » dans la description.
    if embed.description:
        description = str(embed.description).strip()
        description = re.sub(
            r"^(?:\*\*)?SentriX\s*[•/|-]\s*[^\n*]+(?:\*\*)?\s*\n+",
            "",
            description,
            flags=re.IGNORECASE,
        ).strip()
        embed.description = sx_embeds.clip(description, 4096) or None

    # Les noms de fields sont de l'interface ; les valeurs peuvent contenir le message,
    # la bio, une raison ou un emoji de l'utilisateur et restent donc intactes.
    existing = list(embed.fields)
    embed.clear_fields()
    for field in existing[:25]:
        name = _clean_label(field.name, 256, "Information") or "Information"
        value = sx_embeds.clip(field.value, 1024) or "—"
        long_name = name.casefold() in {
            "raison", "motif", "message", "contenu", "avant", "après", "apres",
            "description", "permissions", "changements", "transcript", "pièces jointes",
            "pieces jointes",
        }
        inline = bool(field.inline) and not long_name and len(value) <= 140 and value.count("\n") <= 1
        embed.add_field(name=name, value=value, inline=inline)

    # Une seule identité : la couleur + le footer. On enlève les auteurs « SentriX • ... »
    # qui ajoutaient une ligne verticale inutile. Un auteur métier personnalisé est gardé.
    author = getattr(embed, "author", None)
    author_name = str(getattr(author, "name", "") or "")
    if author_name and author_name.casefold().startswith("sentrix"):
        embed.remove_author()
    elif author_name:
        icon_url = getattr(author, "icon_url", None)
        url = getattr(author, "url", None)
        cleaned = _clean_label(author_name, 120, "")
        if cleaned:
            embed.set_author(name=cleaned, icon_url=icon_url or None, url=url or None)

    footer_text = str(getattr(getattr(embed, "footer", None), "text", "") or "")
    page_match = re.search(r"Page\s+\d+\s*/\s*\d+", footer_text, flags=re.IGNORECASE)
    final_footer = f"{page_match.group(0)} • SentriX" if page_match else "SentriX"
    embed.set_footer(text=final_footer)

    # Les timestamps ordinaires sont retirés : Discord affiche déjà l'heure du message.
    # Les logs ont leur champ Date explicite et cohérent.
    if not log_type:
        embed.timestamp = None

    command_name = str(getattr(command, "qualified_name", "") or "").casefold()
    important = command_name in {
        "help", "profile", "userinfo", "serverinfo", "roleinfo", "botinfo",
        "config-view", "setup",
    }
    resolved_category = str(category or "").casefold()
    if (important or resolved_category in {"profile"}) and not getattr(embed.image, "url", None):
        embed.set_image(url=sx_embeds.SENTRIX_BANNER_URL)
    return embed


def _style_view(view: discord.ui.View | None) -> discord.ui.View | None:
    """Retire les emojis décoratifs sans casser les boutons emoji-only fonctionnels."""
    if view is None:
        return None
    for item in list(getattr(view, "children", ()) or ()):
        if isinstance(item, discord.ui.Button):
            if item.label:
                item.label = _clean_label(item.label, 80, "Action") or "Action"
                # Si le bouton a déjà un vrai libellé, l'emoji est décoratif.
                item.emoji = None
        elif isinstance(item, discord.ui.Select):
            if item.placeholder:
                item.placeholder = _clean_label(item.placeholder, 120, "Choisis une option...")
            for option in list(getattr(item, "options", ()) or ()):
                option.label = _clean_label(option.label, 100, "Option") or "Option"
                if option.description:
                    option.description = _clean_label(option.description, 100, "") or None
                # Les menus de help/config sont de l'interface. Les menus métier peuvent
                # garder leurs emojis si le texte de l'option est vide, ce qui est rare.
                if option.label:
                    option.emoji = None
    return view


def _install_central_style(bot: commands.Bot) -> None:
    # Tous les anciens helpers qui appellent premium_style passent maintenant par la
    # fabrique V70, sans rajouter une nouvelle identité visuelle.
    premium_style.style_embed = _style_embed
    premium_style.style_view = _style_view
    for key in list(premium_style.COLORS):
        premium_style.COLORS[key] = sx_embeds.SENTRIX_COLOR

    # Les commandes Context.send qui ne passent pas par premium_style sont normalisées ici.
    try:
        import main
        context_cls = main.SentriXContext
    except Exception:
        context_cls = None
    if context_cls is None or getattr(context_cls.send, "_sentrix_visual_v70", False):
        return

    original_send = context_cls.send

    async def send_v70(self, *args, **kwargs):
        command = getattr(self, "command", None)
        embed = kwargs.get("embed")
        if isinstance(embed, discord.Embed):
            kwargs["embed"] = _style_embed(
                embed,
                command=command,
                guild=getattr(self, "guild", None),
            )
        if kwargs.get("embeds"):
            kwargs["embeds"] = [
                _style_embed(item, command=command, guild=getattr(self, "guild", None))
                if isinstance(item, discord.Embed) else item
                for item in kwargs["embeds"]
            ]
        if "view" in kwargs:
            kwargs["view"] = _style_view(kwargs.get("view"))
        return await original_send(self, *args, **kwargs)

    send_v70._sentrix_visual_v70 = True
    send_v70._sentrix_original = original_send
    context_cls.send = send_v70


# ---------------------------------------------------------------------------
# Help compact en embed — catégories, pages, recherche, aucune emoji.
# ---------------------------------------------------------------------------

_SHORT_DESCRIPTIONS = {
    "help": "Voir les commandes",
    "setup": "Configurer le serveur",
    "ping": "Voir la latence",
    "avatar": "Voir un avatar",
    "userinfo": "Voir un membre",
    "serverinfo": "Voir le serveur",
    "roleinfo": "Voir un rôle",
    "channelinfo": "Voir un salon",
    "ban": "Bannir un membre",
    "unban": "Débannir un membre",
    "kick": "Expulser un membre",
    "mute": "Rendre un membre muet",
    "unmute": "Retirer le mute",
    "warn": "Avertir un membre",
    "warnings": "Voir les avertissements",
    "clear": "Supprimer des messages",
    "lock": "Verrouiller un salon",
    "unlock": "Déverrouiller un salon",
    "ticket": "Gérer les tickets",
    "balance": "Voir son argent",
    "daily": "Récupérer le bonus quotidien",
    "work": "Gagner de l'argent",
    "pay": "Envoyer de l'argent",
    "inventory": "Voir son inventaire",
    "shop": "Voir la boutique",
    "level": "Voir son niveau",
    "profile": "Voir son profil",
    "sentrix": "Parler avec SentriX",
    "image": "Générer une image",
    "play": "Lire une musique",
    "pause": "Mettre en pause",
    "skip": "Passer la musique",
    "stop": "Arrêter la musique",
    "giveaway": "Gérer un giveaway",
    "rps": "Jouer à pierre-feuille-ciseaux",
    "guess-number": "Jouer à Guess Number",
}


def _short_description(command: commands.Command | None, app_description: str = "") -> str:
    if command is not None:
        root = str(command.qualified_name or command.name).split(" ", 1)[0].casefold()
        if root in _SHORT_DESCRIPTIONS:
            return _SHORT_DESCRIPTIONS[root]
        raw = command.description or command.help or app_description
    else:
        raw = app_description
    text = _clean_label(raw, 68, "Commande SentriX") or "Commande SentriX"
    # Une seule petite phrase : coupe aussi les anciennes explications après le premier point.
    first = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0].strip()
    return sx_embeds.clip(first.rstrip("."), 58)


def _slash_roots(bot: commands.Bot) -> dict[str, Any]:
    try:
        roots = bot.tree.get_commands(guild=None, type=discord.AppCommandType.chat_input)
    except Exception:
        roots = bot.tree.get_commands(guild=None)
    return {
        str(getattr(item, "name", "") or "").casefold(): item
        for item in roots
        if str(getattr(item, "name", "") or "").strip()
    }


def _help_entries(bot: commands.Bot, prefix: str, is_staff: bool):
    slash = _slash_roots(bot)
    rows: list[tuple[str, str, str, str]] = []
    seen: set[str] = set()

    for command in bot.commands:
        if command.parent is not None or getattr(command, "hidden", False):
            continue
        if not is_staff and _is_staff_command(command):
            continue
        name = str(command.name or "").casefold()
        if not name or name in seen:
            continue
        seen.add(name)
        slash_item = slash.get("nick" if name == "nickname" else name)
        slash_name = str(getattr(slash_item, "name", "") or "") if slash_item else ""
        if slash_name:
            access = f"`/{slash_name}`  `{prefix}{name}`"
        else:
            access = f"`{prefix}{name}`"
        rows.append((
            _category_key(command),
            _command_category(command),
            access,
            _short_description(command, getattr(slash_item, "description", "") if slash_item else ""),
        ))

    # Slash-only roots restent visibles.
    for name, item in slash.items():
        if name in seen:
            continue
        command = bot.get_command(name)
        if command is not None and not is_staff and _is_staff_command(command):
            continue
        rows.append((
            _category_key(command),
            _command_category(command),
            f"`/{name}`",
            _short_description(command, getattr(item, "description", "")),
        ))

    rows.sort(key=lambda row: (row[1].casefold(), row[2].casefold()))
    return rows


def _help_pages(rows, *, category_key: str | None = None, title: str | None = None) -> list[discord.Embed]:
    selected = [row for row in rows if category_key is None or row[0] == category_key]
    category_name = title or (selected[0][1] if selected else "Commandes")
    chunks = [selected[index:index + 9] for index in range(0, len(selected), 9)] or [[]]
    pages: list[discord.Embed] = []
    for page_number, chunk in enumerate(chunks, start=1):
        lines = [f"{access} — {description}" for _key, _cat, access, description in chunk]
        embed = sx_embeds.help_embed(
            category_name,
            "\n".join(lines) if lines else "Aucune commande dans cette catégorie.",
        )
        embed.set_footer(text=f"Page {page_number}/{len(chunks)} • SentriX")
        pages.append(embed)
    return pages


def _help_home(rows) -> discord.Embed:
    categories: OrderedDict[str, tuple[str, int]] = OrderedDict()
    for key, name, _access, _description in rows:
        label, count = categories.get(key, (name, 0))
        categories[key] = (label, count + 1)
    category_lines = [f"**{name}** — {count}" for name, count in categories.values()]
    embed = sx_embeds.help_embed(
        "Commandes",
        "Choisis une catégorie ou utilise Rechercher.\nLes commandes / et + utiles restent disponibles.",
    )
    if category_lines:
        embed.add_field(name="Catégories", value="\n".join(category_lines[:20]), inline=False)
    embed.set_footer(text=f"{len(rows)} commandes • SentriX")
    return embed


async def _help_guard(interaction: discord.Interaction, author_id: int) -> bool:
    if interaction.user.id == author_id:
        return True
    await interaction.response.send_message("Ce panneau appartient à une autre personne.", ephemeral=True)
    return False


class HelpSearchModal(discord.ui.Modal):
    def __init__(self, bot: commands.Bot, prefix: str, author_id: int, rows):
        super().__init__(title="Rechercher une commande")
        self.bot = bot
        self.prefix = prefix
        self.author_id = author_id
        self.rows = rows
        self.query = discord.ui.TextInput(label="Nom ou mot-clé", placeholder="ban, ticket, image, logs...", max_length=50)
        self.add_item(self.query)

    async def on_submit(self, interaction: discord.Interaction):
        if not await _help_guard(interaction, self.author_id):
            return
        needle = _clean_label(self.query.value, 50).casefold()
        matches = [row for row in self.rows if needle in f"{row[1]} {row[2]} {row[3]}".casefold()]
        pages = _help_pages(matches, title=f"Recherche : {_clean_label(self.query.value, 28)}")
        view = HelpPagesView(self.bot, self.prefix, self.author_id, self.rows, pages)
        view.message = interaction.message
        await interaction.response.edit_message(embed=pages[0], view=view)


class HelpCategorySelect(discord.ui.Select):
    def __init__(self, bot: commands.Bot, prefix: str, author_id: int, rows):
        self.bot = bot
        self.prefix = prefix
        self.author_id = author_id
        self.rows = rows
        categories: OrderedDict[str, tuple[str, int]] = OrderedDict()
        for key, name, _access, _description in rows:
            label, count = categories.get(key, (name, 0))
            categories[key] = (label, count + 1)
        options = [discord.SelectOption(label="Toutes les commandes", value=_HELP_ALL, description=f"{len(rows)} commandes")]
        for key, (name, count) in categories.items():
            options.append(discord.SelectOption(label=name[:100], value=key, description=f"{count} commandes"))
        super().__init__(placeholder="Choisis une catégorie...", options=options[:25], row=0)

    async def callback(self, interaction: discord.Interaction):
        if not await _help_guard(interaction, self.author_id):
            return
        selected = self.values[0]
        if selected == _HELP_ALL:
            pages = _help_pages(self.rows, title="Toutes les commandes")
        else:
            pages = _help_pages(self.rows, category_key=selected)
        view = HelpPagesView(self.bot, self.prefix, self.author_id, self.rows, pages)
        view.message = interaction.message
        await interaction.response.edit_message(embed=pages[0], view=view)


class _HelpBase(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=180)
        self.author_id = author_id
        self.message: discord.Message | None = None

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class HelpHomeView(_HelpBase):
    def __init__(self, bot: commands.Bot, prefix: str, author_id: int, rows):
        super().__init__(author_id)
        self.bot, self.prefix, self.rows = bot, prefix, rows
        self.add_item(HelpCategorySelect(bot, prefix, author_id, rows))
        search = discord.ui.Button(label="Rechercher", style=discord.ButtonStyle.primary, row=1)
        close = discord.ui.Button(label="Fermer", style=discord.ButtonStyle.secondary, row=1)

        async def search_callback(interaction: discord.Interaction):
            if await _help_guard(interaction, author_id):
                await interaction.response.send_modal(HelpSearchModal(bot, prefix, author_id, rows))

        async def close_callback(interaction: discord.Interaction):
            if not await _help_guard(interaction, author_id):
                return
            await interaction.response.defer()
            try:
                await interaction.message.delete()
            except discord.HTTPException:
                pass

        search.callback = search_callback
        close.callback = close_callback
        self.add_item(search)
        self.add_item(close)


class HelpPagesView(_HelpBase):
    def __init__(self, bot: commands.Bot, prefix: str, author_id: int, rows, pages):
        super().__init__(author_id)
        self.bot, self.prefix, self.rows = bot, prefix, rows
        self.pages = pages or [_help_home(rows)]
        self.index = 0
        self.add_item(HelpCategorySelect(bot, prefix, author_id, rows))
        previous = discord.ui.Button(label="Précédent", style=discord.ButtonStyle.secondary, row=1)
        home = discord.ui.Button(label="Accueil", style=discord.ButtonStyle.primary, row=1)
        next_button = discord.ui.Button(label="Suivant", style=discord.ButtonStyle.secondary, row=1)
        search = discord.ui.Button(label="Rechercher", style=discord.ButtonStyle.secondary, row=1)

        def refresh():
            previous.disabled = self.index <= 0
            next_button.disabled = self.index >= len(self.pages) - 1

        async def previous_callback(interaction: discord.Interaction):
            if not await _help_guard(interaction, author_id): return
            self.index = max(0, self.index - 1); refresh()
            await interaction.response.edit_message(embed=self.pages[self.index], view=self)

        async def next_callback(interaction: discord.Interaction):
            if not await _help_guard(interaction, author_id): return
            self.index = min(len(self.pages) - 1, self.index + 1); refresh()
            await interaction.response.edit_message(embed=self.pages[self.index], view=self)

        async def home_callback(interaction: discord.Interaction):
            if not await _help_guard(interaction, author_id): return
            view = HelpHomeView(bot, prefix, author_id, rows); view.message = interaction.message
            await interaction.response.edit_message(embed=_help_home(rows), view=view)

        async def search_callback(interaction: discord.Interaction):
            if await _help_guard(interaction, author_id):
                await interaction.response.send_modal(HelpSearchModal(bot, prefix, author_id, rows))

        previous.callback = previous_callback
        next_button.callback = next_callback
        home.callback = home_callback
        search.callback = search_callback
        self.add_item(previous); self.add_item(home); self.add_item(next_button); self.add_item(search)
        refresh()


def _install_help(bot: commands.Bot) -> None:
    command = bot.get_command("help")
    if command is None:
        return

    async def help_callback(*args, **kwargs):
        del kwargs
        ctx = next((value for value in args if isinstance(value, commands.Context)), None)
        if ctx is None:
            raise TypeError("Contexte Discord introuvable pour help")
        prefix = str(getattr(ctx, "clean_prefix", None) or "+")
        try:
            if ctx.guild is not None:
                prefix = str(getattr(ctx.bot, "prefix_cache", {}).get(ctx.guild.id) or prefix)
        except Exception:
            pass
        is_staff = False
        try:
            if isinstance(ctx.author, discord.Member):
                is_staff = bool(ctx.author.guild_permissions.administrator)
            if not is_staff:
                import config
                is_staff = ctx.author.id in config.OWNER_IDS
        except Exception:
            pass
        rows = _help_entries(ctx.bot, prefix, is_staff)
        embed = _help_home(rows)
        view = HelpHomeView(ctx.bot, prefix, ctx.author.id, rows)
        message = await ctx.send(embed=embed, view=view)
        view.message = message
        return message

    help_callback.__name__ = "help_cmd"
    help_callback._sentrix_visual_v70 = True
    command.callback = help_callback
    command.params = OrderedDict()
    command.usage = ""
    command.description = "Voir les commandes SentriX."
    command.help = command.description
    command.hidden = False
    checks = getattr(command, "checks", None)
    if isinstance(checks, list):
        checks.clear()
    app = getattr(command, "app_command", None)
    if app is not None:
        try:
            app.description = "Voir les commandes SentriX."
            app_checks = getattr(app, "checks", None)
            if isinstance(app_checks, list):
                app_checks.clear()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Logs : embed Discord standard + fields inline, une seule taille graphique.
# ---------------------------------------------------------------------------

def _norm(value: object) -> str:
    text = str(value or "").casefold()
    for old, new in (("é", "e"), ("è", "e"), ("ê", "e"), ("à", "a"), ("ù", "u"), ("ô", "o"), ("î", "i"), ("ç", "c")):
        text = text.replace(old, new)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _log_title(source: discord.Embed, log_type: str) -> str:
    raw = _short_title(source)
    generic = {
        "messages": "Message enregistré",
        "members": "Membre",
        "roles": "Rôle",
        "server": "Salon",
        "voice": "Vocal",
        "moderation": "Modération",
        "tickets": "Ticket",
        "automod": "Sécurité",
        "security": "Sécurité",
    }
    if not raw or raw.casefold() in {"information", "journal", "log"}:
        raw = generic.get(str(log_type), "Journal")
    return raw


def _source_time(source: discord.Embed) -> datetime:
    stamp = source.timestamp
    if stamp is None:
        return datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        return stamp.replace(tzinfo=timezone.utc)
    return stamp


def _log_fields(source: discord.Embed) -> list[tuple[str, str, bool | None]]:
    result: list[tuple[str, str, bool | None]] = []
    seen: set[tuple[str, str]] = set()
    long_tokens = {
        "raison", "motif", "message", "contenu", "avant", "apres", "description",
        "permissions", "changements", "transcript", "pieces jointes", "piece jointe",
    }

    for field in list(source.fields):
        name = _clean_label(field.name, 70, "Information") or "Information"
        value = sx_embeds.clip(field.value, 1024)
        if not value:
            continue
        key = (_norm(name), str(value))
        if key in seen:
            continue
        seen.add(key)
        normalized = _norm(name)
        full = any(token == normalized or token in normalized for token in long_tokens)
        inline = False if full else (len(value) <= 150 and value.count("\n") <= 1)
        result.append((name, value, inline))

    # Si un ancien log n'avait que sa description, on ne perd pas l'information.
    if not result and source.description:
        description = sx_embeds.clip(source.description, 1024)
        if description:
            result.append(("Détails", description, False))
    return result[:18]


def _log_key(guild: discord.Guild, log_type: str, source: discord.Embed) -> str:
    try:
        from . import log_dedupe_guard_v55 as v55
        return v55._source_key(guild, str(log_type), source)
    except Exception:
        ids = re.findall(r"(?<!\d)(\d{15,22})(?!\d)", " ".join(
            [str(source.title or ""), str(source.description or "")]
            + [f"{field.name}:{field.value}" for field in source.fields[:6]]
        ))
        return f"{guild.id}:{log_type}:{_norm(source.title)}:{':'.join(ids[:3])}"


def _log_priority(log_type: str, source: discord.Embed) -> int:
    try:
        from . import log_dedupe_guard_v55 as v55
        return int(v55._priority(str(log_type), source))
    except Exception:
        return min(50, len(source.fields) * 5)


def _needs_log_grace(log_type: str, source: discord.Embed, priority: int) -> bool:
    try:
        from . import log_dedupe_guard_v55 as v55
        return bool(v55._needs_grace(str(log_type), source, priority))
    except Exception:
        return False


def _prune_logs() -> None:
    now = time.monotonic()
    for key, expires in list(_LOG_RECENT.items())[:5000]:
        if expires <= now:
            _LOG_RECENT.pop(key, None)


class CopyLogIdButton(discord.ui.Button):
    def __init__(self, label: str, value: int, index: int):
        clean = _clean_label(str(label).replace("Copier", ""), 60, "ID") or "ID"
        if not clean.casefold().startswith("id"):
            clean = "ID " + clean
        super().__init__(label=clean, style=discord.ButtonStyle.secondary, custom_id=f"sentrix_v70_log:{index}:{value}")
        self.value = int(value)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(str(self.value), ephemeral=True)


def _log_view(guild: discord.Guild, log_type: str, source: discord.Embed) -> discord.ui.View | None:
    try:
        from . import log_preferred_style_v30 as v30
        items = v30._button_items(guild, str(log_type), source)
    except Exception:
        items = []
    if not items:
        return None
    view = discord.ui.View(timeout=6 * 60 * 60)
    seen: set[int] = set()
    for index, (label, value) in enumerate(items[:3]):
        try:
            value = int(value)
        except (TypeError, ValueError):
            continue
        if value in seen:
            continue
        seen.add(value)
        view.add_item(CopyLogIdButton(str(label), value, index))
    return view if view.children else None


def _render_log(guild: discord.Guild, log_type: str, source: discord.Embed) -> discord.Embed:
    return sx_embeds.log_embed(
        _log_title(source, log_type),
        fields=_log_fields(source),
        event_time=_source_time(source),
        banner=True,
    )


def _install_logs(bot: commands.Bot) -> None:
    async def send_log_v70(
        inner_bot,
        guild: discord.Guild,
        log_type: str,
        source: discord.Embed,
        file: discord.File | None = None,
    ) -> bool:
        if not isinstance(source, discord.Embed):
            return False
        try:
            setting = await log_service.get_log_setting(inner_bot, guild.id, str(log_type))
        except Exception:
            logger.exception("V70 : configuration de log illisible guild=%s type=%s", guild.id, log_type)
            return False
        if not setting.get("enabled"):
            return False
        ok, _reason = log_service.validate_channel(guild, setting.get("channel_id"), needs_file=file is not None)
        if not ok:
            return False
        channel = guild.get_channel(setting.get("channel_id"))
        if not isinstance(channel, discord.TextChannel):
            return False

        key = _log_key(guild, str(log_type), source)
        priority = _log_priority(str(log_type), source)
        if _needs_log_grace(str(log_type), source, priority):
            await asyncio.sleep(1.35)
        _prune_logs()
        if _LOG_RECENT.get(key, 0.0) > time.monotonic():
            logger.debug("V70 : doublon log supprimé %s", key)
            return False

        embed = _render_log(guild, str(log_type), source)
        view = _log_view(guild, str(log_type), source)
        kwargs: dict[str, Any] = {
            "embed": embed,
            "allowed_mentions": discord.AllowedMentions.none(),
        }
        if view is not None:
            kwargs["view"] = view
        if file is not None:
            kwargs["file"] = file
        try:
            await channel.send(**kwargs)
        except (discord.Forbidden, discord.HTTPException):
            logger.warning("V70 : log non envoyé guild=%s type=%s", guild.id, log_type, exc_info=True)
            return False
        _LOG_RECENT[key] = time.monotonic() + _LOG_TTL
        return True

    send_log_v70._sentrix_visual_v70 = True
    log_service.send_log = send_log_v70

    # Les tickets avec salon de log dédié contournaient historiquement log_service.
    ticket_cog = bot.get_cog("Tickets")
    if ticket_cog is not None and hasattr(ticket_cog, "log_action"):
        current = ticket_cog.log_action
        if not getattr(current, "_sentrix_visual_v70", False):
            async def ticket_log_v70(self, guild: discord.Guild, source: discord.Embed, log_channel_id: int | None = None):
                if log_channel_id:
                    channel = guild.get_channel(int(log_channel_id))
                    if isinstance(channel, discord.TextChannel):
                        embed = _render_log(guild, "tickets", source)
                        view = _log_view(guild, "tickets", source)
                        kwargs = {"embed": embed, "allowed_mentions": discord.AllowedMentions.none()}
                        if view is not None:
                            kwargs["view"] = view
                        try:
                            await channel.send(**kwargs)
                            return
                        except (discord.Forbidden, discord.HTTPException):
                            pass
                await log_service.send_log(self.bot, guild, "tickets", source)

            ticket_log_v70._sentrix_visual_v70 = True
            ticket_log_v70._sentrix_original = current
            ticket_cog.log_action = types.MethodType(ticket_log_v70, ticket_cog)


# ---------------------------------------------------------------------------
# Finalisation.
# ---------------------------------------------------------------------------

def install(bot: commands.Bot) -> None:
    global _INSTALLED
    _install_central_style(bot)
    _install_help(bot)
    _install_logs(bot)

    # Les anciens renderers restent importables pour compatibilité, mais ne sont plus la
    # source de vérité. On désactive explicitement les deux couches temporaires précédentes.
    bot._sentrix_help_v65_disabled_by_v70 = True
    bot._sentrix_log_v56_disabled_by_v70 = True
    _INSTALLED = True
    logger.info("SentriX V70 actif : embeds centralisés, help compact, logs standards horizontaux.")


__all__ = ["install"]
