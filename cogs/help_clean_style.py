"""Style final et sans emoji pour toute l'interface +help SentriX.

Cette couche est volontairement installee apres le moteur de langue. Elle devient donc
la source visuelle finale de +help, sans modifier le registre, les permissions ou la
logique des commandes.
"""
from __future__ import annotations

import logging
from typing import Iterable

import discord
from discord.ext import commands

from utils import embeds

logger = logging.getLogger("bot.help-clean-style")

ACCENT = 0x6C5CE7
_ALL_VALUE = "__sentrix_clean_all__"


def _brand(title: str, description: str = "") -> discord.Embed:
    embed = embeds.brand(title, description)
    embed.colour = discord.Colour(ACCENT)
    return embed


def _visual_category(key: str) -> str:
    return {
        "ai": "ai",
        "economy": "economy",
        "levels": "levels",
        "games": "games",
        "music": "music",
        "events": "events",
        "social": "invites",
        "tickets": "tickets",
        "sanctions": "moderation",
        "moderation": "moderation",
        "security": "security",
        "configuration": "configuration",
        "server": "configuration",
        "roles": "configuration",
        "embeds": "configuration",
        "stats": "logs",
        "owner": "premium",
    }.get(str(key or "").casefold(), "brand")


def _apply_category_colour(embed: discord.Embed, key: str) -> discord.Embed:
    from utils import premium_style
    embed.colour = discord.Colour(premium_style.COLORS[_visual_category(key)])
    return embed


def _language(bot: commands.Bot, guild_id: int | None) -> str:
    from . import language_runtime
    return language_runtime.cached_language(bot, guild_id)


def _category_text(category, language: str) -> tuple[str, str]:
    from . import language_runtime
    return language_runtime._category_text(category, language)


def _help_entries(bot: commands.Bot, is_staff: bool):
    from . import language_runtime
    return language_runtime._help_entries(bot, is_staff)


def _usage(command: commands.Command, prefix: str, language: str) -> str:
    from . import language_runtime
    return language_runtime._command_usage(command, prefix, language)


def _summary(command: commands.Command, language: str) -> str:
    from . import language_runtime
    return language_runtime._summary(command, language)


def _is_staff(command: commands.Command) -> bool:
    from . import utility
    return utility.is_staff_command(command)


def _command_line(utility, command: commands.Command, prefix: str, language: str, number: int | None = None) -> str:
    del utility
    usage = _usage(command, prefix, language)
    access = "STAFF" if _is_staff(command) else ("MEMBER" if language == "en" else "MEMBRE")
    index = f"`{number:02d}`  " if number is not None else ""
    return f"{index}`{usage}`  `{access}`\n{_summary(command, language)}"


def _help_home(bot: commands.Bot, guild: discord.Guild | None, prefix: str, is_staff: bool, language: str) -> discord.Embed:
    entries = _help_entries(bot, is_staff)
    total = sum(len(commands_list) for _, commands_list in entries)
    category_count = len(entries)
    if language == "en":
        shortcuts = [f"`{prefix}profile`", f"`{prefix}ticket`", f"`{prefix}daily`"]
        if is_staff:
            shortcuts.append(f"`{prefix}setup`")
        embed = _brand(
            "SENTRIX / HELP",
            (
                f"**{total} commands** • prefix `{prefix}`\n"
                "Select a category below or use search.\n\n"
                f"Quick access: {'  '.join(shortcuts)}"
            ),
        )
        embed.set_footer(text=f"SentriX • {category_count} categories")
    else:
        shortcuts = [f"`{prefix}profile`", f"`{prefix}ticket`", f"`{prefix}daily`"]
        if is_staff:
            shortcuts.append(f"`{prefix}setup`")
        embed = _brand(
            "SENTRIX / AIDE",
            (
                f"**{total} commandes** • préfixe `{prefix}`\n"
                "Choisis une catégorie ci-dessous ou utilise la recherche.\n\n"
                f"Accès rapides : {'  '.join(shortcuts)}"
            ),
        )
        embed.set_footer(text=f"SentriX • {category_count} catégories")
    return embed


def _category_pages(bot: commands.Bot, prefix: str, language: str, category, commands_list: list[commands.Command]) -> list[discord.Embed]:
    del bot
    name, summary = _category_text(category, language)
    chunks = [commands_list[index:index + 8] for index in range(0, len(commands_list), 8)] or [[]]
    pages: list[discord.Embed] = []
    for page_number, chunk in enumerate(chunks, start=1):
        # La fiche détaillée reste accessible avec +help <commande>. La page de
        # catégorie ne montre donc que les syntaxes afin de rester aussi courte qu'un ticket.
        lines = [f"`{_usage(command, prefix, language)}`" for command in chunk]
        body = summary + (("\n\n" + "\n".join(lines)) if lines else "")
        embed = _apply_category_colour(_brand(f"SENTRIX / {name.upper()}", body), category.key)
        if language == "en":
            embed.set_footer(text=f"Page {page_number}/{len(chunks)} | {len(commands_list)} commands | <required> [optional]")
        else:
            embed.set_footer(text=f"Page {page_number}/{len(chunks)} | {len(commands_list)} commandes | <obligatoire> [facultatif]")
        pages.append(embed)
    return pages


def _all_pages(bot: commands.Bot, prefix: str, language: str, is_staff: bool) -> list[discord.Embed]:
    commands_with_category: list[tuple[object, commands.Command]] = []
    for category, command_list in _help_entries(bot, is_staff):
        commands_with_category.extend((category, command) for command in command_list)
    chunks = [commands_with_category[index:index + 12] for index in range(0, len(commands_with_category), 12)] or [[]]
    pages: list[discord.Embed] = []
    for page_number, chunk in enumerate(chunks, start=1):
        lines: list[str] = []
        base_index = (page_number - 1) * 12
        for offset, (category, command) in enumerate(chunk, start=1):
            category_name, _ = _category_text(category, language)
            lines.append(f"`{base_index + offset:02d}` `{_usage(command, prefix, language)}` • {category_name}")
        title = "SENTRIX / ALL COMMANDS" if language == "en" else "SENTRIX / TOUTES LES COMMANDES"
        description = "\n".join(lines) if lines else ("No command." if language == "en" else "Aucune commande.")
        embed = _brand(title, description)
        embed.set_footer(text=f"Page {page_number}/{len(chunks)} | {len(commands_with_category)} " + ("commands" if language == "en" else "commandes"))
        pages.append(embed)
    return pages


def _text_has_emoji(value: str | None) -> bool:
    if not value:
        return False
    for char in str(value):
        code = ord(char)
        if 0x1F000 <= code <= 0x1FAFF or 0x2600 <= code <= 0x27BF:
            return True
    return False


def _embed_has_emoji(embed: discord.Embed) -> bool:
    values: list[str | None] = [embed.title, embed.description]
    values.extend(field.name for field in embed.fields)
    values.extend(field.value for field in embed.fields)
    if embed.footer:
        values.append(embed.footer.text)
    return any(_text_has_emoji(value) for value in values)


class CleanHelpSearchModal(discord.ui.Modal):
    def __init__(self, bot: commands.Bot, prefix: str, is_staff: bool, language: str, author_id: int):
        super().__init__(title="Search a command" if language == "en" else "Rechercher une commande")
        self.bot, self.prefix, self.is_staff, self.language, self.author_id = bot, prefix, is_staff, language, author_id
        self.query = discord.ui.TextInput(label="Name or keyword" if language == "en" else "Nom ou mot-cle", placeholder="ticket, ban, music..." if language == "en" else "ticket, bannir, musique...", max_length=60)
        self.add_item(self.query)

    async def on_submit(self, interaction: discord.Interaction):
        from . import help_complete, language_runtime, utility
        needle = language_runtime._strip_accents(str(self.query.value).casefold())
        results: list[commands.Command] = []
        for command in help_complete._registered_commands(utility, self.bot, self.is_staff):
            haystack = " ".join((command.qualified_name, language_runtime.localized_command_name(command, self.language), language_runtime.localized_command_name(command, language_runtime.LANG_FR), language_runtime.localized_command_name(command, language_runtime.LANG_EN), _summary(command, self.language)))
            if needle in language_runtime._strip_accents(haystack.casefold()):
                results.append(command)
        if not results:
            text = "No command found for this search." if self.language == "en" else "Aucune commande trouvee pour cette recherche."
            return await interaction.response.edit_message(embed=_brand("SENTRIX / SEARCH" if self.language == "en" else "SENTRIX / RECHERCHE", text), view=CleanHelpHomeView(self.bot, self.prefix, self.is_staff, self.language, self.author_id))
        chunks = [results[index:index + 8] for index in range(0, len(results), 8)]
        pages: list[discord.Embed] = []
        for page_number, chunk in enumerate(chunks, start=1):
            embed = _brand(
                "SENTRIX / SEARCH" if self.language == "en" else "SENTRIX / RECHERCHE",
                "\n".join(f"`{_usage(command, self.prefix, self.language)}`" for command in chunk),
            )
            embed.set_footer(text=f"Page {page_number}/{len(chunks)} | {len(results)}")
            pages.append(embed)
        home = _help_home(self.bot, interaction.guild, self.prefix, self.is_staff, self.language)
        await interaction.response.edit_message(embed=pages[0], view=CleanHelpPagesView(self.bot, self.prefix, self.is_staff, self.language, self.author_id, pages, home))


class CleanHelpSelect(discord.ui.Select):
    def __init__(self, bot: commands.Bot, prefix: str, is_staff: bool, language: str, author_id: int):
        self.bot, self.prefix, self.is_staff, self.language, self.author_id = bot, prefix, is_staff, language, author_id
        self.entries = _help_entries(bot, is_staff)
        total = sum(len(commands_list) for _, commands_list in self.entries)
        all_label = "All commands" if language == "en" else "Toutes les commandes"
        options: list[discord.SelectOption] = [discord.SelectOption(label=all_label, value=_ALL_VALUE, description=f"{total} " + ("active commands" if language == "en" else "commandes actives"))]
        for category, commands_list in self.entries:
            name, summary = _category_text(category, language)
            unit = "commands" if language == "en" else "commandes"
            options.append(discord.SelectOption(label=name[:100], value=category.key, description=f"{len(commands_list)} {unit} | {summary}"[:100]))
        super().__init__(placeholder="Select a category..." if language == "en" else "Selectionne une categorie...", options=options[:25], row=0)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("This menu belongs to another user." if self.language == "en" else "Ce menu appartient a une autre personne.", ephemeral=True)
        selected = self.values[0]
        if selected == _ALL_VALUE:
            pages = _all_pages(self.bot, self.prefix, self.language, self.is_staff)
        else:
            matching = next(((category, commands_list) for category, commands_list in self.entries if category.key == selected), None)
            if matching is None:
                return await interaction.response.defer()
            pages = _category_pages(self.bot, self.prefix, self.language, *matching)
        home = _help_home(self.bot, interaction.guild, self.prefix, self.is_staff, self.language)
        await interaction.response.edit_message(embed=pages[0], view=CleanHelpPagesView(self.bot, self.prefix, self.is_staff, self.language, self.author_id, pages, home))


class CleanHelpHomeView(discord.ui.View):
    def __init__(self, bot: commands.Bot, prefix: str, is_staff: bool, language: str, author_id: int):
        super().__init__(timeout=180)
        self.bot, self.prefix, self.is_staff, self.language, self.author_id = bot, prefix, is_staff, language, author_id
        self.add_item(CleanHelpSelect(bot, prefix, is_staff, language, author_id))
        search = discord.ui.Button(label="Search" if language == "en" else "Rechercher", style=discord.ButtonStyle.secondary, row=1)
        async def search_callback(interaction: discord.Interaction):
            if interaction.user.id != author_id:
                return await interaction.response.send_message("This menu belongs to another user." if language == "en" else "Ce menu appartient a une autre personne.", ephemeral=True)
            await interaction.response.send_modal(CleanHelpSearchModal(bot, prefix, is_staff, language, author_id))
        search.callback = search_callback
        self.add_item(search)


class CleanHelpPagesView(discord.ui.View):
    def __init__(self, bot: commands.Bot, prefix: str, is_staff: bool, language: str, author_id: int, pages: list[discord.Embed], home_embed: discord.Embed):
        super().__init__(timeout=180)
        self.bot, self.prefix, self.is_staff, self.language, self.author_id = bot, prefix, is_staff, language, author_id
        self.pages, self.home_embed, self.index = pages, home_embed, 0
        self.add_item(CleanHelpSelect(bot, prefix, is_staff, language, author_id))
        previous = discord.ui.Button(label="Previous" if language == "en" else "Precedent", style=discord.ButtonStyle.secondary, row=1, disabled=len(pages) <= 1)
        home = discord.ui.Button(label="Home" if language == "en" else "Accueil", style=discord.ButtonStyle.primary, row=1)
        next_button = discord.ui.Button(label="Next" if language == "en" else "Suivant", style=discord.ButtonStyle.secondary, row=1, disabled=len(pages) <= 1)
        search = discord.ui.Button(label="Search" if language == "en" else "Rechercher", style=discord.ButtonStyle.secondary, row=2)
        def refresh():
            previous.disabled = self.index <= 0
            next_button.disabled = self.index >= len(self.pages) - 1
        async def previous_callback(interaction: discord.Interaction):
            if interaction.user.id != author_id:
                return await interaction.response.send_message("This menu belongs to another user." if language == "en" else "Ce menu appartient a une autre personne.", ephemeral=True)
            self.index = max(0, self.index - 1); refresh(); await interaction.response.edit_message(embed=self.pages[self.index], view=self)
        async def home_callback(interaction: discord.Interaction):
            if interaction.user.id != author_id:
                return await interaction.response.send_message("This menu belongs to another user." if language == "en" else "Ce menu appartient a une autre personne.", ephemeral=True)
            await interaction.response.edit_message(embed=self.home_embed, view=CleanHelpHomeView(bot, prefix, is_staff, language, author_id))
        async def next_callback(interaction: discord.Interaction):
            if interaction.user.id != author_id:
                return await interaction.response.send_message("This menu belongs to another user." if language == "en" else "Ce menu appartient a une autre personne.", ephemeral=True)
            self.index = min(len(self.pages) - 1, self.index + 1); refresh(); await interaction.response.edit_message(embed=self.pages[self.index], view=self)
        async def search_callback(interaction: discord.Interaction):
            if interaction.user.id != author_id:
                return await interaction.response.send_message("This menu belongs to another user." if language == "en" else "Ce menu appartient a une autre personne.", ephemeral=True)
            await interaction.response.send_modal(CleanHelpSearchModal(bot, prefix, is_staff, language, author_id))
        previous.callback, home.callback, next_button.callback, search.callback = previous_callback, home_callback, next_callback, search_callback
        self.add_item(previous); self.add_item(home); self.add_item(next_button); self.add_item(search); refresh()


async def _clean_help_callback(cog, ctx: commands.Context, *, commande: str = None):
    from . import help_complete, language_runtime, utility
    bot = cog.bot
    language = await language_runtime.get_language(bot, ctx.guild.id if ctx.guild else None)
    conf = await bot.db.get_guild_config(ctx.guild.id) if ctx.guild else None
    prefix = conf["prefix"] if conf and conf["prefix"] else "+"
    is_staff = await cog._user_is_staff(ctx)
    if commande:
        command = language_runtime.resolve_localized_command(bot, commande, language)
        if command is None or (utility.is_staff_command(command) and not is_staff):
            if language == "en":
                return await ctx.send(embed=_brand("SENTRIX / COMMAND NOT FOUND", f"Command `{commande}` was not found or you do not have access. Use `{prefix}help` to return."))
            return await ctx.send(embed=_brand("SENTRIX / COMMANDE INTROUVABLE", f"La commande `{commande}` est introuvable ou tu n'y as pas acces. Utilise `{prefix}aide` pour revenir."))
        category = help_complete._category_for(command)
        category_name, _ = _category_text(category, language)
        command_title = language_runtime._title(command, language).upper()
        embed = _brand(f"SENTRIX / {command_title}", _summary(command, language))
        _apply_category_colour(embed, category.key)
        parameters: list[str] = []
        for name, parameter in getattr(command, "clean_params", {}).items():
            if name in {"ctx", "context", "interaction", "self"}:
                continue
            display = language_runtime._param_name(name, language)
            status = ("required" if getattr(parameter, "required", False) else "optional") if language == "en" else ("obligatoire" if getattr(parameter, "required", False) else "facultatif")
            parameters.append(f"- **{display}** - {status}")
        if language == "en":
            embed.add_field(name="SYNTAX", value=f"`{_usage(command, prefix, language)}`", inline=False)
            embed.add_field(name="PARAMETERS", value="\n".join(parameters) if parameters else "No parameters.", inline=False)
            embed.add_field(name="ACCESS", value=f"{category_name} | {'Staff only' if utility.is_staff_command(command) else 'Members'}", inline=False)
            embed.set_footer(text="SentriX | Command sheet")
        else:
            embed.add_field(name="SYNTAXE", value=f"`{_usage(command, prefix, language)}`", inline=False)
            embed.add_field(name="PARAMETRES", value="\n".join(parameters) if parameters else "Aucun parametre.", inline=False)
            embed.add_field(name="ACCES", value=f"{category_name} | {'Staff uniquement' if utility.is_staff_command(command) else 'Membres'}", inline=False)
            embed.set_footer(text="SentriX | Fiche commande")
        return await ctx.send(embed=embed)
    home = _help_home(bot, ctx.guild, prefix, is_staff, language)
    return await ctx.send(embed=home, view=CleanHelpHomeView(bot, prefix, is_staff, language, ctx.author.id))


_clean_help_callback._sentrix_help_clean_v8 = True


def _fallback_home(utility, bot: commands.Bot, guild, prefix: str, is_staff: bool) -> discord.Embed:
    del utility
    return _help_home(bot, guild, prefix, is_staff, _language(bot, guild.id if guild else None))


def _fallback_pages(utility, bot: commands.Bot, prefix: str, entries: Iterable, *, all_mode: bool):
    del utility
    language = _language(bot, None)
    if all_mode:
        flattened: list[tuple[object, commands.Command]] = []
        for category, command_list in entries:
            flattened.extend((category, command) for command in command_list)
        chunks = [flattened[index:index + 12] for index in range(0, len(flattened), 12)] or [[]]
        pages: list[discord.Embed] = []
        for page_number, chunk in enumerate(chunks, start=1):
            lines = []
            for offset, (category, command) in enumerate(chunk, start=1):
                name, _ = _category_text(category, language)
                lines.append(f"`{(page_number - 1) * 12 + offset:02d}` `{_usage(command, prefix, language)}` • {name}")
            embed = _brand("SENTRIX / TOUTES LES COMMANDES", "\n".join(lines)); embed.set_footer(text=f"Page {page_number}/{len(chunks)}"); pages.append(embed)
        return pages
    pages: list[discord.Embed] = []
    for category, command_list in entries:
        pages.extend(_category_pages(bot, prefix, language, category, command_list))
    return pages


def _fallback_command_line(utility, command, prefix: str, slash_names: set[str], number: int | None = None):
    del slash_names
    return _command_line(utility, command, prefix, _language(getattr(command.cog, "bot", None), None) if getattr(command, "cog", None) else "fr", number)


def install(bot: commands.Bot) -> None:
    """Réaffirme le rendu V8 après chaque passage du moteur de langue.

    Le loader SentriX exécute les finaliseurs après chaque extension. Le moteur de langue
    peut donc relier +help à son callback entre deux passages. L'ancienne garde idempotente
    sur le bot empêchait alors V8 de reprendre la priorité. Les affectations ci-dessous sont
    idempotentes et volontairement répétées : V8 doit toujours être la DERNIÈRE couche.
    """
    help_command = bot.get_command("help")
    if help_command is None:
        return

    from . import help_complete, language_runtime, utility

    language_runtime._command_line = _command_line
    language_runtime._help_home = _help_home
    language_runtime._build_category_pages = _category_pages
    language_runtime.LanguageHelpSearchModal = CleanHelpSearchModal
    language_runtime.LanguageHelpSelect = CleanHelpSelect
    language_runtime.LanguageHelpHomeView = CleanHelpHomeView
    language_runtime.LanguageHelpPagesView = CleanHelpPagesView
    language_runtime._localized_help_callback = _clean_help_callback

    help_command.callback = _clean_help_callback
    help_command._sentrix_language_help = True
    help_command._sentrix_help_clean_v8 = True

    help_complete._home_embed = _fallback_home
    help_complete._build_pages = _fallback_pages
    help_complete._compact_command_line = _fallback_command_line
    try:
        help_complete.CategorySpec.label = property(lambda self: self.name)
    except Exception:
        logger.debug("Impossible de remplacer CategorySpec.label", exc_info=True)

    cleaned_labels = {}
    for cog_name, label in utility.CATEGORY_LABELS.items():
        _, clean = utility.split_category_label(label)
        cleaned_labels[cog_name] = clean
    utility.CATEGORY_LABELS = cleaned_labels

    first_install = not getattr(bot, "_sentrix_help_clean_v8", False)
    bot._sentrix_help_clean_v8 = True
    if first_install:
        logger.info("+help V9 actif : centre visuel, catégories colorées et navigation premium.")
