"""SentriX V65 — aide finale compacte, texte pur, sans emoji ni embed.

Cette couche ne change aucune logique métier. Elle remplace seulement la présentation de
+help / /help après toutes les anciennes couches visuelles afin qu'aucun ancien renderer
ne puisse remettre le grand embed historique.
"""
from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass

import discord
from discord import app_commands
from discord.ext import commands


_ALL = "__sentrix_v65_all__"
_CUSTOM_EMOJI_RE = re.compile(r"<a?:[A-Za-z0-9_]{2,32}:\d+>")


def _clean(value: object, limit: int = 90) -> str:
    text = _CUSTOM_EMOJI_RE.sub("", str(value or ""))
    chars: list[str] = []
    for char in text:
        code = ord(char)
        if (
            0x1F000 <= code <= 0x1FAFF
            or 0x2600 <= code <= 0x27BF
            or 0x2300 <= code <= 0x23FF
            or code in {0xFE0F, 0x200D}
        ):
            continue
        chars.append(char)
    text = re.sub(r"\s+", " ", "".join(chars)).strip(" -•·|:/")
    if len(text) > limit:
        text = text[: max(1, limit - 1)].rstrip() + "…"
    return text


def _sanitize_command_metadata(bot: commands.Bot) -> None:
    """Retire les emojis des noms de catégories/descriptions affichées par Discord."""
    for command in bot.walk_commands():
        description = _clean(getattr(command, "description", ""), 100)
        help_text = _clean(getattr(command, "help", ""), 180)
        if description:
            command.description = description
        if help_text:
            command.help = help_text
        app = getattr(command, "app_command", None)
        if app is not None:
            try:
                cleaned = _clean(getattr(app, "description", ""), 100)
                if cleaned:
                    app.description = cleaned
            except Exception:
                pass

    def visit_app(item) -> None:
        try:
            cleaned = _clean(getattr(item, "description", ""), 100)
            if cleaned:
                item.description = cleaned
        except Exception:
            pass
        for child in getattr(item, "commands", ()) or ():
            visit_app(child)

    try:
        roots = bot.tree.get_commands(guild=None, type=discord.AppCommandType.chat_input)
    except Exception:
        roots = bot.tree.get_commands(guild=None)
    for root in roots:
        visit_app(root)


@dataclass(frozen=True)
class Entry:
    key: str
    display: str
    description: str
    category_key: str
    category_name: str
    slash: bool


def _category(command: commands.Command | None) -> tuple[str, str]:
    if command is None:
        return "other", "Autres"
    try:
        from . import help_complete

        category = help_complete._category_for(command)
        return str(category.key), _clean(category.name, 70) or "Autres"
    except Exception:
        cog = getattr(command, "cog", None)
        return "other", _clean(getattr(cog, "qualified_name", "Autres"), 70) or "Autres"


def _is_staff_command(command: commands.Command) -> bool:
    try:
        from . import utility
        return bool(utility.is_staff_command(command))
    except Exception:
        return False


def _app_roots(bot: commands.Bot):
    try:
        return list(bot.tree.get_commands(guild=None, type=discord.AppCommandType.chat_input))
    except Exception:
        return [
            item for item in bot.tree.get_commands(guild=None)
            if isinstance(item, (app_commands.Command, app_commands.Group))
        ]


def _entries(bot: commands.Bot, prefix: str, is_staff: bool) -> list[Entry]:
    result: list[Entry] = []
    slash_names: set[str] = set()

    for item in _app_roots(bot):
        name = str(getattr(item, "name", "") or "").casefold().strip()
        if not name:
            continue
        command = bot.get_command(name)
        if command is None and name == "nick":
            command = bot.get_command("nickname")
        if command is not None and _is_staff_command(command) and not is_staff:
            continue
        slash_names.add(name)
        category_key, category_name = _category(command)
        description = _clean(
            getattr(item, "description", "")
            or getattr(command, "description", "")
            or getattr(command, "help", "")
            or "Commande SentriX.",
            72,
        )
        result.append(
            Entry(name, f"/{name}", description, category_key, category_name, True)
        )

    for command in bot.commands:
        if command.parent is not None or getattr(command, "hidden", False):
            continue
        name = str(getattr(command, "name", "") or "").casefold().strip()
        if not name or name in slash_names:
            continue
        if _is_staff_command(command) and not is_staff:
            continue
        category_key, category_name = _category(command)
        description = _clean(
            getattr(command, "description", "")
            or getattr(command, "help", "")
            or "Commande SentriX.",
            72,
        )
        result.append(
            Entry(name, f"{prefix}{name}", description, category_key, category_name, False)
        )

    # Les slash restent toujours en premier, puis les + qui ne les doublonnent pas.
    result.sort(key=lambda item: (0 if item.slash else 1, item.category_name.casefold(), item.key))
    return result


def _home(prefix: str) -> str:
    return (
        "SentriX — Commandes\n"
        "Choisis une catégorie ou utilise Rechercher.\n"
        f"Les / sont prioritaires. Les commandes {prefix} restent disponibles sans doublon."
    )


def _pages(entries: list[Entry], title: str) -> list[str]:
    # Six commandes maximum par page : aucune page géante.
    chunks = [entries[index:index + 6] for index in range(0, len(entries), 6)] or [[]]
    pages: list[str] = []
    total_pages = len(chunks)
    for page_number, chunk in enumerate(chunks, start=1):
        lines = [title]
        if chunk:
            for item in chunk:
                desc = item.description or "Commande SentriX."
                lines.append(f"`{item.display}` — {desc}")
        else:
            lines.append("Aucune commande.")
        if total_pages > 1:
            lines.append(f"Page {page_number}/{total_pages}")
        pages.append("\n".join(lines)[:1900])
    return pages


async def _edit(interaction: discord.Interaction, content: str, view: discord.ui.View) -> None:
    if not interaction.response.is_done():
        await interaction.response.edit_message(content=content, embed=None, view=view)
    elif interaction.message is not None:
        await interaction.message.edit(content=content, embed=None, view=view)


async def _guard(interaction: discord.Interaction, author_id: int) -> bool:
    if interaction.user.id == author_id:
        return True
    if interaction.response.is_done():
        await interaction.followup.send("Ce menu appartient à une autre personne.", ephemeral=True)
    else:
        await interaction.response.send_message("Ce menu appartient à une autre personne.", ephemeral=True)
    return False


class SearchModal(discord.ui.Modal):
    def __init__(self, bot: commands.Bot, prefix: str, author_id: int, entries: list[Entry], home: str):
        super().__init__(title="Rechercher une commande")
        self.bot = bot
        self.prefix = prefix
        self.author_id = author_id
        self.entries = entries
        self.home = home
        self.query = discord.ui.TextInput(
            label="Nom ou mot-clé",
            placeholder="ticket, ban, image, logs...",
            max_length=50,
        )
        self.add_item(self.query)

    async def on_submit(self, interaction: discord.Interaction):
        if not await _guard(interaction, self.author_id):
            return
        needle = _clean(self.query.value, 50).casefold()
        matches = [
            item for item in self.entries
            if needle in f"{item.key} {item.description} {item.category_name}".casefold()
        ]
        if not matches:
            view = HomeView(self.bot, self.prefix, self.author_id, self.entries, self.home)
            view.message = interaction.message
            return await _edit(interaction, "SentriX — Recherche\nAucune commande trouvée.", view)
        pages = _pages(matches, f"SentriX — Recherche : {_clean(self.query.value, 30)}")
        view = PagesView(self.bot, self.prefix, self.author_id, self.entries, self.home, pages)
        view.message = interaction.message
        await _edit(interaction, pages[0], view)


class CategorySelect(discord.ui.Select):
    def __init__(self, bot: commands.Bot, prefix: str, author_id: int, entries: list[Entry], home: str):
        self.bot = bot
        self.prefix = prefix
        self.author_id = author_id
        self.entries = entries
        self.home = home

        categories: OrderedDict[str, tuple[str, int]] = OrderedDict()
        for item in entries:
            if item.category_key not in categories:
                categories[item.category_key] = (item.category_name, 0)
            label, count = categories[item.category_key]
            categories[item.category_key] = (label, count + 1)

        options = [
            discord.SelectOption(
                label="Toutes les commandes",
                value=_ALL,
                description=f"{len(entries)} commandes",
            )
        ]
        for key, (label, count) in categories.items():
            options.append(
                discord.SelectOption(
                    label=_clean(label, 90) or "Autres",
                    value=key,
                    description=f"{count} commandes",
                )
            )

        super().__init__(placeholder="Choisis une catégorie...", options=options[:25], row=0)

    async def callback(self, interaction: discord.Interaction):
        if not await _guard(interaction, self.author_id):
            return
        selected = self.values[0]
        if selected == _ALL:
            subset = self.entries
            title = "SentriX — Toutes les commandes"
        else:
            subset = [item for item in self.entries if item.category_key == selected]
            title = f"SentriX — {subset[0].category_name if subset else 'Autres'}"
        pages = _pages(subset, title)
        view = PagesView(self.bot, self.prefix, self.author_id, self.entries, self.home, pages)
        view.message = interaction.message
        await _edit(interaction, pages[0], view)


class BaseView(discord.ui.View):
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


class HomeView(BaseView):
    def __init__(self, bot: commands.Bot, prefix: str, author_id: int, entries: list[Entry], home: str):
        super().__init__(author_id)
        self.bot = bot
        self.prefix = prefix
        self.entries = entries
        self.home = home
        self.add_item(CategorySelect(bot, prefix, author_id, entries, home))

        search = discord.ui.Button(label="Rechercher", style=discord.ButtonStyle.primary, row=1)
        close = discord.ui.Button(label="Fermer", style=discord.ButtonStyle.secondary, row=1)

        async def search_callback(interaction: discord.Interaction):
            if not await _guard(interaction, author_id):
                return
            await interaction.response.send_modal(SearchModal(bot, prefix, author_id, entries, home))

        async def close_callback(interaction: discord.Interaction):
            if not await _guard(interaction, author_id):
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


class PagesView(BaseView):
    def __init__(self, bot: commands.Bot, prefix: str, author_id: int, entries: list[Entry], home: str, pages: list[str]):
        super().__init__(author_id)
        self.bot = bot
        self.prefix = prefix
        self.entries = entries
        self.home = home
        self.pages = pages or [home]
        self.index = 0
        self.add_item(CategorySelect(bot, prefix, author_id, entries, home))

        previous = discord.ui.Button(label="Précédent", style=discord.ButtonStyle.secondary, row=1)
        home_button = discord.ui.Button(label="Accueil", style=discord.ButtonStyle.primary, row=1)
        next_button = discord.ui.Button(label="Suivant", style=discord.ButtonStyle.secondary, row=1)
        search = discord.ui.Button(label="Rechercher", style=discord.ButtonStyle.secondary, row=1)
        close = discord.ui.Button(label="Fermer", style=discord.ButtonStyle.secondary, row=1)

        def refresh() -> None:
            previous.disabled = self.index <= 0
            next_button.disabled = self.index >= len(self.pages) - 1

        async def previous_callback(interaction: discord.Interaction):
            if not await _guard(interaction, author_id):
                return
            self.index = max(0, self.index - 1)
            refresh()
            await _edit(interaction, self.pages[self.index], self)

        async def next_callback(interaction: discord.Interaction):
            if not await _guard(interaction, author_id):
                return
            self.index = min(len(self.pages) - 1, self.index + 1)
            refresh()
            await _edit(interaction, self.pages[self.index], self)

        async def home_callback(interaction: discord.Interaction):
            if not await _guard(interaction, author_id):
                return
            view = HomeView(bot, prefix, author_id, entries, home)
            view.message = interaction.message
            await _edit(interaction, home, view)

        async def search_callback(interaction: discord.Interaction):
            if not await _guard(interaction, author_id):
                return
            await interaction.response.send_modal(SearchModal(bot, prefix, author_id, entries, home))

        async def close_callback(interaction: discord.Interaction):
            if not await _guard(interaction, author_id):
                return
            await interaction.response.defer()
            try:
                await interaction.message.delete()
            except discord.HTTPException:
                pass

        previous.callback = previous_callback
        home_button.callback = home_callback
        next_button.callback = next_callback
        search.callback = search_callback
        close.callback = close_callback
        self.add_item(previous)
        self.add_item(home_button)
        self.add_item(next_button)
        self.add_item(search)
        self.add_item(close)
        refresh()


async def _is_staff(ctx: commands.Context) -> bool:
    cog = ctx.bot.get_cog("Utility")
    check = getattr(cog, "_user_is_staff", None) if cog is not None else None
    if callable(check):
        try:
            return bool(await check(ctx))
        except Exception:
            pass
    if isinstance(ctx.author, discord.Member):
        return bool(ctx.author.guild_permissions.manage_guild)
    return False


async def _prefix(bot: commands.Bot, ctx: commands.Context) -> str:
    if ctx.guild is None:
        return "+"
    cached = getattr(bot, "prefix_cache", {}).get(ctx.guild.id)
    if cached:
        return str(cached)
    try:
        conf = await bot.db.get_guild_config(ctx.guild.id)
        return str(conf["prefix"] if conf and conf["prefix"] else "+")
    except Exception:
        return "+"


async def _send_initial(ctx: commands.Context, content: str, view: discord.ui.View):
    # Ne passe pas par les wrappers visuels de Context.send : c'est ce qui garantit
    # qu'aucun ancien style ne transforme à nouveau +help en embed.
    interaction = getattr(ctx, "interaction", None)
    if interaction is not None:
        if interaction.response.is_done():
            await interaction.followup.send(content, view=view, ephemeral=False)
            try:
                return await interaction.original_response()
            except Exception:
                return None
        await interaction.response.send_message(content, view=view)
        try:
            return await interaction.original_response()
        except Exception:
            return None

    if ctx.channel is None:
        return None
    return await ctx.channel.send(
        content=content,
        view=view,
        allowed_mentions=discord.AllowedMentions.none(),
    )


def install(bot: commands.Bot) -> None:
    _sanitize_command_metadata(bot)
    command = bot.get_command("help")
    if command is None:
        return

    async def compact_help(*args, **kwargs):
        del kwargs
        ctx = next((value for value in args if isinstance(value, commands.Context)), None)
        if ctx is None:
            raise TypeError("Context Discord introuvable pour help")
        prefix = await _prefix(ctx.bot, ctx)
        staff = await _is_staff(ctx)
        entries = _entries(ctx.bot, prefix, staff)
        home = _home(prefix)
        view = HomeView(ctx.bot, prefix, ctx.author.id, entries, home)
        message = await _send_initial(ctx, home, view)
        view.message = message
        return message

    compact_help.__name__ = "help_cmd"
    compact_help._sentrix_help_v65 = True
    command.callback = compact_help
    command.params = OrderedDict()
    command.usage = ""
    command.description = "Afficher les commandes SentriX."
    command.help = command.description
    command.hidden = False

    checks = getattr(command, "checks", None)
    if isinstance(checks, list):
        checks.clear()
    app = getattr(command, "app_command", None)
    app_checks = getattr(app, "checks", None)
    if isinstance(app_checks, list):
        app_checks.clear()
    if app is not None:
        try:
            app.description = "Afficher les commandes SentriX."
        except Exception:
            pass

    bot._sentrix_help_v65 = True


__all__ = ["install"]
