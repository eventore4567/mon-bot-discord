"""Aide canonique SentriX : simple, recherchable et sans décoration emoji.

Une seule page d'accueil courte. Les nombreuses commandes + restent faciles à trouver grâce
au menu de catégories, à la recherche et à `+help <commande>`, sans afficher un inventaire
énorme dès l'ouverture.
"""
from __future__ import annotations

import re
import logging

import discord
from discord.ext import commands

from utils import embeds

logger = logging.getLogger("bot.help-simple")
ALL_VALUE = "__sentrix_help_all__"
ACCENT = 0x6C5CE7


def _embed(title: str, description: str = "") -> discord.Embed:
    result = embeds.brand(title, description)
    result.colour = discord.Colour(ACCENT)
    result.remove_author()
    result.set_thumbnail(url=None)
    return result


def _language(bot: commands.Bot, guild_id: int | None) -> str:
    try:
        from . import language_runtime
        return language_runtime.cached_language(bot, guild_id)
    except Exception:
        return "fr"


def _prefix(bot: commands.Bot, guild_id: int | None) -> str:
    cached = getattr(bot, "prefix_cache", {}).get(guild_id) if guild_id else None
    return str(cached or "+")


def _entries(bot: commands.Bot, is_staff: bool):
    from . import help_complete, utility
    return help_complete._category_entries(utility, bot, is_staff)


def _registered(bot: commands.Bot, is_staff: bool):
    from . import help_complete, utility
    return help_complete._registered_commands(utility, bot, is_staff)


def _category_name(category, language: str) -> str:
    try:
        from . import language_runtime
        name, _ = language_runtime._category_text(category, language)
        return str(name)
    except Exception:
        return str(getattr(category, "name", "Commandes"))


def _summary(command: commands.Command, language: str) -> str:
    try:
        from . import language_runtime
        value = language_runtime._summary(command, language)
    except Exception:
        value = command.description or command.help or ""
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    return value[:130] + ("…" if len(value) > 130 else "")


def _usage(command: commands.Command, prefix: str) -> str:
    parts = [f"{prefix}{command.qualified_name}"]
    for name, parameter in getattr(command, "clean_params", {}).items():
        if name in {"ctx", "context", "interaction", "self"}:
            continue
        parts.append(f"<{name}>" if getattr(parameter, "required", False) else f"[{name}]")
    return " ".join(parts)


def _slash_names(bot: commands.Bot) -> set[str]:
    names: set[str] = set()
    def visit(command, parent: str = ""):
        qualified = f"{parent} {command.name}".strip()
        names.add(qualified)
        for child in getattr(command, "commands", ()) or ():
            visit(child, qualified)
    for command in bot.tree.get_commands():
        visit(command)
    return names


def _home(bot: commands.Bot, prefix: str, language: str) -> discord.Embed:
    if language == "en":
        description = (
            "Choose a category or use Search to find a command.\n"
            f"For a specific command: `{prefix}help ban`."
        )
        title = "Help"
        footer = f"Prefix {prefix}"
    else:
        description = (
            "Choisis une catégorie ou utilise Rechercher pour trouver une commande.\n"
            f"Pour une commande précise : `{prefix}help ban`."
        )
        title = "Aide"
        footer = f"Préfixe {prefix}"
    result = _embed(title, description)
    result.set_footer(text=footer)
    return result


def _command_pages(bot: commands.Bot, prefix: str, language: str, category, command_list: list[commands.Command]) -> list[discord.Embed]:
    slash = _slash_names(bot)
    name = _category_name(category, language)
    pages: list[discord.Embed] = []
    chunks = [command_list[i:i + 10] for i in range(0, len(command_list), 10)] or [[]]
    for index, chunk in enumerate(chunks, start=1):
        lines = []
        for command in chunk:
            prefixed = _usage(command, prefix)
            root = command.qualified_name.split(" ", 1)[0]
            access = f" /{command.qualified_name}" if root in slash or command.qualified_name in slash else ""
            lines.append(f"`{prefixed}`{access}\n{_summary(command, language)}")
        result = _embed(name, "\n\n".join(lines) if lines else "Aucune commande.")
        result.set_footer(text=f"Page {index}/{len(chunks)}")
        pages.append(result)
    return pages


def _all_pages(bot: commands.Bot, prefix: str, language: str, is_staff: bool) -> list[discord.Embed]:
    commands_list = _registered(bot, is_staff)
    pages: list[discord.Embed] = []
    chunks = [commands_list[i:i + 14] for i in range(0, len(commands_list), 14)] or [[]]
    for index, chunk in enumerate(chunks, start=1):
        lines = [f"`{_usage(command, prefix)}`" for command in chunk]
        title = "All commands" if language == "en" else "Toutes les commandes"
        result = _embed(title, "\n".join(lines) if lines else "Aucune commande.")
        result.set_footer(text=f"Page {index}/{len(chunks)} • {len(commands_list)}")
        pages.append(result)
    return pages


async def _guard(interaction: discord.Interaction, author_id: int, language: str) -> bool:
    if interaction.user.id == author_id:
        return True
    text = "This menu belongs to another user." if language == "en" else "Ce menu appartient à une autre personne."
    await interaction.response.send_message(text, ephemeral=True)
    return False


async def _edit(interaction: discord.Interaction, embed: discord.Embed, view: discord.ui.View) -> None:
    await interaction.response.edit_message(content=None, embed=embed, view=view)


class SearchModal(discord.ui.Modal):
    def __init__(self, bot: commands.Bot, prefix: str, is_staff: bool, language: str, author_id: int):
        super().__init__(title="Search" if language == "en" else "Rechercher")
        self.bot, self.prefix, self.is_staff = bot, prefix, is_staff
        self.language, self.author_id = language, author_id
        self.query = discord.ui.TextInput(
            label="Command or keyword" if language == "en" else "Commande ou mot-clé",
            placeholder="ticket, ban, logs, image...",
            max_length=60,
        )
        self.add_item(self.query)

    async def on_submit(self, interaction: discord.Interaction):
        if not await _guard(interaction, self.author_id, self.language):
            return
        needle = str(self.query.value).casefold().strip()
        results = []
        for command in _registered(self.bot, self.is_staff):
            aliases = " ".join(getattr(command, "aliases", ()) or ())
            text = f"{command.qualified_name} {aliases} {_summary(command, self.language)}".casefold()
            if needle in text:
                results.append(command)
        if not results:
            result = _embed(
                "Search" if self.language == "en" else "Recherche",
                "No command found." if self.language == "en" else "Aucune commande trouvée.",
            )
            view = HomeView(self.bot, self.prefix, self.is_staff, self.language, self.author_id)
            return await _edit(interaction, result, view)
        fake_category = type("Category", (), {"name": "Search" if self.language == "en" else "Recherche"})()
        pages = _command_pages(self.bot, self.prefix, self.language, fake_category, results)
        view = PagesView(self.bot, self.prefix, self.is_staff, self.language, self.author_id, pages)
        await _edit(interaction, pages[0], view)


class CategorySelect(discord.ui.Select):
    def __init__(self, bot: commands.Bot, prefix: str, is_staff: bool, language: str, author_id: int):
        self.bot, self.prefix, self.is_staff = bot, prefix, is_staff
        self.language, self.author_id = language, author_id
        self.entries = _entries(bot, is_staff)
        options = [discord.SelectOption(label="All commands" if language == "en" else "Toutes les commandes", value=ALL_VALUE)]
        for category, command_list in self.entries:
            options.append(discord.SelectOption(
                label=_category_name(category, language)[:100],
                value=category.key,
                description=(f"{len(command_list)} commands" if language == "en" else f"{len(command_list)} commandes")[:100],
            ))
        super().__init__(
            placeholder="Choose a category..." if language == "en" else "Choisis une catégorie...",
            options=options[:25],
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        if not await _guard(interaction, self.author_id, self.language):
            return
        selected = self.values[0]
        if selected == ALL_VALUE:
            pages = _all_pages(self.bot, self.prefix, self.language, self.is_staff)
        else:
            match = next(((cat, cmds) for cat, cmds in self.entries if cat.key == selected), None)
            if match is None:
                return await interaction.response.defer()
            pages = _command_pages(self.bot, self.prefix, self.language, *match)
        view = PagesView(self.bot, self.prefix, self.is_staff, self.language, self.author_id, pages)
        await _edit(interaction, pages[0], view)


class HomeView(discord.ui.View):
    def __init__(self, bot: commands.Bot, prefix: str, is_staff: bool, language: str, author_id: int):
        super().__init__(timeout=180)
        self.bot, self.prefix, self.is_staff = bot, prefix, is_staff
        self.language, self.author_id = language, author_id
        self.add_item(CategorySelect(bot, prefix, is_staff, language, author_id))
        search = discord.ui.Button(label="Search" if language == "en" else "Rechercher", style=discord.ButtonStyle.secondary, row=1)
        close = discord.ui.Button(label="Close" if language == "en" else "Fermer", style=discord.ButtonStyle.danger, row=1)
        async def search_callback(interaction):
            if await _guard(interaction, author_id, language):
                await interaction.response.send_modal(SearchModal(bot, prefix, is_staff, language, author_id))
        async def close_callback(interaction):
            if not await _guard(interaction, author_id, language):
                return
            await interaction.response.defer()
            try:
                await interaction.message.delete()
            except discord.HTTPException:
                pass
        search.callback, close.callback = search_callback, close_callback
        self.add_item(search); self.add_item(close)


class PagesView(discord.ui.View):
    def __init__(self, bot: commands.Bot, prefix: str, is_staff: bool, language: str, author_id: int, pages: list[discord.Embed]):
        super().__init__(timeout=180)
        self.bot, self.prefix, self.is_staff = bot, prefix, is_staff
        self.language, self.author_id, self.pages, self.index = language, author_id, pages, 0
        self.add_item(CategorySelect(bot, prefix, is_staff, language, author_id))
        previous = discord.ui.Button(label="Previous" if language == "en" else "Précédent", style=discord.ButtonStyle.secondary, row=1)
        home = discord.ui.Button(label="Home" if language == "en" else "Accueil", style=discord.ButtonStyle.primary, row=1)
        next_button = discord.ui.Button(label="Next" if language == "en" else "Suivant", style=discord.ButtonStyle.secondary, row=1)
        search = discord.ui.Button(label="Search" if language == "en" else "Rechercher", style=discord.ButtonStyle.secondary, row=1)
        close = discord.ui.Button(label="Close" if language == "en" else "Fermer", style=discord.ButtonStyle.danger, row=1)
        def refresh():
            previous.disabled = self.index == 0
            next_button.disabled = self.index >= len(self.pages) - 1
        async def prev_cb(interaction):
            if not await _guard(interaction, author_id, language): return
            self.index = max(0, self.index - 1); refresh(); await _edit(interaction, self.pages[self.index], self)
        async def home_cb(interaction):
            if not await _guard(interaction, author_id, language): return
            await _edit(interaction, _home(bot, prefix, language), HomeView(bot, prefix, is_staff, language, author_id))
        async def next_cb(interaction):
            if not await _guard(interaction, author_id, language): return
            self.index = min(len(self.pages)-1, self.index+1); refresh(); await _edit(interaction, self.pages[self.index], self)
        async def search_cb(interaction):
            if await _guard(interaction, author_id, language):
                await interaction.response.send_modal(SearchModal(bot, prefix, is_staff, language, author_id))
        async def close_cb(interaction):
            if not await _guard(interaction, author_id, language): return
            await interaction.response.defer()
            try: await interaction.message.delete()
            except discord.HTTPException: pass
        previous.callback, home.callback, next_button.callback = prev_cb, home_cb, next_cb
        search.callback, close.callback = search_cb, close_cb
        self.add_item(previous); self.add_item(home); self.add_item(next_button); self.add_item(search); self.add_item(close)
        refresh()


async def _callback(cog, ctx: commands.Context, *, commande: str = None):
    from . import language_runtime, utility, help_complete
    bot = cog.bot
    language = await language_runtime.get_language(bot, ctx.guild.id if ctx.guild else None)
    prefix = _prefix(bot, ctx.guild.id if ctx.guild else None)
    is_staff = await cog._user_is_staff(ctx)

    if commande:
        command = language_runtime.resolve_localized_command(bot, commande, language)
        if command is None or (utility.is_staff_command(command) and not is_staff):
            text = "Command not found." if language == "en" else "Commande introuvable."
            return await ctx.send(embed=_embed(text, f"`{commande}`"))
        category = help_complete._category_for(command)
        slash = _slash_names(bot)
        root = command.qualified_name.split(" ", 1)[0]
        access = " /" + command.qualified_name if root in slash or command.qualified_name in slash else ""
        result = _embed(command.qualified_name, _summary(command, language))
        result.add_field(name="Syntax" if language == "en" else "Syntaxe", value=f"`{_usage(command, prefix)}`{access}", inline=False)
        result.add_field(
            name="Access" if language == "en" else "Accès",
            value=("Staff" if utility.is_staff_command(command) else "Members") if language == "en" else ("Staff" if utility.is_staff_command(command) else "Membres"),
            inline=False,
        )
        result.set_footer(text=_category_name(category, language))
        return await ctx.send(embed=result)

    view = HomeView(bot, prefix, is_staff, language, ctx.author.id)
    return await ctx.send(embed=_home(bot, prefix, language), view=view)


_callback._sentrix_help_simple = True


def install(bot: commands.Bot) -> None:
    help_command = bot.get_command("help")
    if help_command is None:
        return
    help_command.callback = _callback
    help_command.hidden = False
    bot._sentrix_help_owner = "cogs.help_simple"
    logger.info("Aide SentriX simple active : accueil court, catégories et recherche, sans emojis.")


__all__ = ["install", "HomeView", "PagesView", "CategorySelect", "SearchModal"]
