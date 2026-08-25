"""SentriX V3 — fondation UX unifiée.

Cette couche ne crée aucune commande Discord et ne touche pas à la logique métier.
Elle est volontairement chargée après les anciennes couches visuelles afin de fournir
une seule expérience finale pour +help et /help : accueil orienté actions, navigation
rapide, recherche, catégories lisibles et pages cohérentes.
"""
from __future__ import annotations

import logging
import math

import discord
from discord.ext import commands

logger = logging.getLogger("bot.sentrix-v3-ux")

ACCENT = 0x8B5CF6
ALL_VALUE = "__sentrix_v3_all__"


def _brand(title: str, description: str = "", *, colour: int = ACCENT) -> discord.Embed:
    from utils import embeds

    embed = embeds.brand(title, description)
    embed.colour = discord.Colour(colour)
    return embed


def _category_emoji(category) -> str:
    value = str(getattr(category, "emoji", "") or "").strip()
    return value if value else "✦"


def _home_embed(
    bot: commands.Bot,
    guild: discord.Guild | None,
    prefix: str,
    is_staff: bool,
    language: str,
) -> discord.Embed:
    from . import help_clean_style as clean

    entries = clean._help_entries(bot, is_staff)
    total = sum(len(commands_list) for _, commands_list in entries)
    categories = len(entries)
    slash_roots = len(bot.tree.get_commands())
    latency_ms = max(0, round(float(getattr(bot, "latency", 0.0) or 0.0) * 1000))

    if language == "en":
        embed = _brand(
            "✦ SentriX • Control Center",
            (
                "Everything useful is grouped here. **You do not need to know a command name**: "
                "pick an action, a category, or use search."
            ),
        )
        embed.add_field(
            name="🚀 Start here",
            value=(
                f"`{prefix}help <command>` — detailed help\n"
                f"`{prefix}setup` — configure a server\n"
                "Use the buttons below for the most common areas."
            ),
            inline=False,
        )
        embed.add_field(
            name="✨ Main systems",
            value="🛡️ Security & moderation\n🎫 Tickets & support\n🤖 AI & utilities\n🎮 Community & progression",
            inline=True,
        )
        embed.add_field(
            name="📊 Live",
            value=(
                f"**{total}** visible commands\n"
                f"**{categories}** categories\n"
                f"**{slash_roots}** slash roots\n"
                f"**{latency_ms} ms** gateway"
            ),
            inline=True,
        )
        embed.add_field(
            name="⌕ Find anything",
            value="Press **Search** and type a command, an alias, or a keyword such as `ticket`, `ban`, `logs` or `image`.",
            inline=False,
        )
        footer = f"SentriX V3 • prefix {prefix} • {categories} categories"
    else:
        embed = _brand(
            "✦ SentriX • Centre de contrôle",
            (
                "Tout ce qui est utile est regroupé ici. **Pas besoin de connaître le nom d’une commande** : "
                "choisis une action, une catégorie ou utilise la recherche."
            ),
        )
        embed.add_field(
            name="🚀 Commencer",
            value=(
                f"`{prefix}help <commande>` — aide détaillée\n"
                f"`{prefix}setup` — configurer un serveur\n"
                "Les boutons ci-dessous ouvrent directement les systèmes les plus utiles."
            ),
            inline=False,
        )
        embed.add_field(
            name="✨ Systèmes principaux",
            value="🛡️ Sécurité & modération\n🎫 Tickets & support\n🤖 IA & utilitaires\n🎮 Communauté & progression",
            inline=True,
        )
        embed.add_field(
            name="📊 En direct",
            value=(
                f"**{total}** commandes visibles\n"
                f"**{categories}** catégories\n"
                f"**{slash_roots}** racines slash\n"
                f"**{latency_ms} ms** gateway"
            ),
            inline=True,
        )
        embed.add_field(
            name="⌕ Trouver n’importe quoi",
            value="Appuie sur **Rechercher** puis écris une commande, un alias ou un mot comme `ticket`, `ban`, `logs` ou `image`.",
            inline=False,
        )
        footer = f"SentriX V3 • préfixe {prefix} • {categories} catégories"

    if bot.user is not None:
        embed.set_author(name="SentriX", icon_url=bot.user.display_avatar.url)
        embed.set_thumbnail(url=bot.user.display_avatar.url)
    embed.set_footer(text=footer)
    return embed


def _command_line(command: commands.Command, prefix: str, language: str) -> str:
    from . import help_clean_style as clean

    usage = clean._usage(command, prefix, language)
    summary = clean._summary(command, language).strip()
    if len(summary) > 118:
        summary = summary[:115].rstrip() + "…"
    staff = clean._is_staff(command)
    badge = "STAFF" if staff else ("MEMBER" if language == "en" else "MEMBRE")
    return f"**`{usage}`**  ·  `{badge}`\n└ {summary}"


def _category_pages(
    bot: commands.Bot,
    prefix: str,
    language: str,
    category,
    commands_list: list[commands.Command],
) -> list[discord.Embed]:
    from . import help_clean_style as clean

    name, summary = clean._category_text(category, language)
    chunks = [commands_list[index:index + 7] for index in range(0, len(commands_list), 7)] or [[]]
    pages: list[discord.Embed] = []
    for page_number, chunk in enumerate(chunks, start=1):
        body = "\n\n".join(_command_line(command, prefix, language) for command in chunk)
        description = summary + (("\n\n" + body) if body else "")
        embed = _brand(f"{_category_emoji(category)} {name}", description)
        clean._apply_category_colour(embed, category.key)
        unit = "commands" if language == "en" else "commandes"
        syntax = "<required> [optional]" if language == "en" else "<obligatoire> [facultatif]"
        embed.set_footer(text=f"SentriX V3 • page {page_number}/{len(chunks)} • {len(commands_list)} {unit} • {syntax}")
        pages.append(embed)
    return pages


def _all_pages(bot: commands.Bot, prefix: str, language: str, is_staff: bool) -> list[discord.Embed]:
    from . import help_clean_style as clean

    flattened: list[tuple[object, commands.Command]] = []
    for category, commands_list in clean._help_entries(bot, is_staff):
        flattened.extend((category, command) for command in commands_list)

    chunks = [flattened[index:index + 10] for index in range(0, len(flattened), 10)] or [[]]
    pages: list[discord.Embed] = []
    for page_number, chunk in enumerate(chunks, start=1):
        lines: list[str] = []
        for offset, (category, command) in enumerate(chunk, start=1):
            name, _summary = clean._category_text(category, language)
            number = (page_number - 1) * 10 + offset
            lines.append(
                f"`{number:02d}` {_category_emoji(category)} **`{clean._usage(command, prefix, language)}`**\n"
                f"└ {name}"
            )
        title = "📚 All commands" if language == "en" else "📚 Toutes les commandes"
        embed = _brand(title, "\n\n".join(lines) if lines else "—")
        unit = "commands" if language == "en" else "commandes"
        embed.set_footer(text=f"SentriX V3 • page {page_number}/{len(chunks)} • {len(flattened)} {unit}")
        pages.append(embed)
    return pages


async def _edit(interaction: discord.Interaction, *, embed: discord.Embed, view: discord.ui.View) -> None:
    from . import help_clean_style as clean

    await clean._edit_help_message(interaction, embed=embed, view=view)


async def _guard_owner(interaction: discord.Interaction, author_id: int, language: str) -> bool:
    if interaction.user.id == author_id:
        return True
    text = "This menu belongs to another user." if language == "en" else "Ce menu appartient à une autre personne."
    if interaction.response.is_done():
        await interaction.followup.send(text, ephemeral=True)
    else:
        await interaction.response.send_message(text, ephemeral=True)
    return False


class V3SearchModal(discord.ui.Modal):
    def __init__(self, bot: commands.Bot, prefix: str, is_staff: bool, language: str, author_id: int):
        super().__init__(title="Search SentriX" if language == "en" else "Rechercher dans SentriX")
        self.bot = bot
        self.prefix = prefix
        self.is_staff = is_staff
        self.language = language
        self.author_id = author_id
        self.query = discord.ui.TextInput(
            label="Command or keyword" if language == "en" else "Commande ou mot-clé",
            placeholder="ticket, ban, logs, image…",
            max_length=60,
        )
        self.add_item(self.query)

    async def on_submit(self, interaction: discord.Interaction):
        from . import help_clean_style as clean, help_complete, language_runtime, utility

        if not await _guard_owner(interaction, self.author_id, self.language):
            return
        needle = language_runtime._strip_accents(str(self.query.value).casefold().strip())
        results: list[commands.Command] = []
        for command in help_complete._registered_commands(utility, self.bot, self.is_staff):
            aliases = " ".join(getattr(command, "aliases", ()) or ())
            haystack = " ".join(
                (
                    command.qualified_name,
                    aliases,
                    language_runtime.localized_command_name(command, self.language),
                    clean._summary(command, self.language),
                )
            )
            if needle in language_runtime._strip_accents(haystack.casefold()):
                results.append(command)

        if not results:
            title = "⌕ No result" if self.language == "en" else "⌕ Aucun résultat"
            text = (
                f"No command matches **{self.query.value}**. Try another keyword."
                if self.language == "en"
                else f"Aucune commande ne correspond à **{self.query.value}**. Essaie un autre mot-clé."
            )
            home = _home_embed(self.bot, interaction.guild, self.prefix, self.is_staff, self.language)
            view = V3HomeView(self.bot, self.prefix, self.is_staff, self.language, self.author_id)
            view.message = interaction.message
            return await _edit(interaction, embed=_brand(title, text), view=view)

        chunks = [results[index:index + 7] for index in range(0, len(results), 7)]
        pages: list[discord.Embed] = []
        for page_number, chunk in enumerate(chunks, start=1):
            embed = _brand(
                f"⌕ {'Search' if self.language == 'en' else 'Recherche'} • {self.query.value}",
                "\n\n".join(_command_line(command, self.prefix, self.language) for command in chunk),
            )
            embed.set_footer(text=f"SentriX V3 • page {page_number}/{len(chunks)} • {len(results)} résultat(s)")
            pages.append(embed)
        home = _home_embed(self.bot, interaction.guild, self.prefix, self.is_staff, self.language)
        view = V3PagesView(self.bot, self.prefix, self.is_staff, self.language, self.author_id, pages, home)
        view.message = interaction.message
        await _edit(interaction, embed=pages[0], view=view)


class V3Select(discord.ui.Select):
    def __init__(self, bot: commands.Bot, prefix: str, is_staff: bool, language: str, author_id: int):
        from . import help_clean_style as clean

        self.bot = bot
        self.prefix = prefix
        self.is_staff = is_staff
        self.language = language
        self.author_id = author_id
        self.entries = clean._help_entries(bot, is_staff)
        total = sum(len(commands_list) for _, commands_list in self.entries)

        options = [
            discord.SelectOption(
                label="All commands" if language == "en" else "Toutes les commandes",
                value=ALL_VALUE,
                emoji="📚",
                description=f"{total} " + ("visible commands" if language == "en" else "commandes visibles"),
            )
        ]
        for category, commands_list in self.entries:
            name, summary = clean._category_text(category, language)
            options.append(
                discord.SelectOption(
                    label=name[:100],
                    value=category.key,
                    emoji=_category_emoji(category),
                    description=(f"{len(commands_list)} • {summary}")[:100],
                )
            )
        placeholder = "Choose what you need…" if language == "en" else "Choisis ce dont tu as besoin…"
        super().__init__(placeholder=placeholder, options=options[:25], row=0)

    async def callback(self, interaction: discord.Interaction):
        if not await _guard_owner(interaction, self.author_id, self.language):
            return
        selected = self.values[0]
        if selected == ALL_VALUE:
            pages = _all_pages(self.bot, self.prefix, self.language, self.is_staff)
        else:
            matching = next(
                ((category, commands_list) for category, commands_list in self.entries if category.key == selected),
                None,
            )
            if matching is None:
                return await interaction.response.defer()
            pages = _category_pages(self.bot, self.prefix, self.language, *matching)
        home = _home_embed(self.bot, interaction.guild, self.prefix, self.is_staff, self.language)
        view = V3PagesView(self.bot, self.prefix, self.is_staff, self.language, self.author_id, pages, home)
        view.message = interaction.message
        await _edit(interaction, embed=pages[0], view=view)


class _V3BaseView(discord.ui.View):
    def __init__(self, *, author_id: int, language: str):
        super().__init__(timeout=180)
        self.author_id = author_id
        self.language = language
        self.message: discord.Message | None = None

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class V3HomeView(_V3BaseView):
    def __init__(self, bot: commands.Bot, prefix: str, is_staff: bool, language: str, author_id: int):
        super().__init__(author_id=author_id, language=language)
        self.bot, self.prefix, self.is_staff = bot, prefix, is_staff
        self.add_item(V3Select(bot, prefix, is_staff, language, author_id))

        quick = (
            (("⚙️", "Setup & logs", "configuration"), ("🛡️", "Sécurité", "security"), ("🔨", "Modération", "moderation"), ("🎫", "Tickets", "tickets"))
            if is_staff and language != "en"
            else (("⚙️", "Setup & logs", "configuration"), ("🛡️", "Security", "security"), ("🔨", "Moderation", "moderation"), ("🎫", "Tickets", "tickets"))
            if is_staff
            else (("🤖", "AI", "ai"), ("🎮", "Games", "games"), ("📈", "Profile", "levels"), ("🎫", "Tickets", "tickets"))
            if language == "en"
            else (("🤖", "IA", "ai"), ("🎮", "Jeux", "games"), ("📈", "Profil", "levels"), ("🎫", "Tickets", "tickets"))
        )

        for emoji, label, key in quick:
            button = discord.ui.Button(label=label, emoji=emoji, style=discord.ButtonStyle.secondary, row=1)

            async def callback(interaction: discord.Interaction, category_key: str = key):
                if not await _guard_owner(interaction, author_id, language):
                    return
                from . import help_clean_style as clean

                matching = next(
                    ((category, commands_list) for category, commands_list in clean._help_entries(bot, is_staff) if category.key == category_key),
                    None,
                )
                if matching is None:
                    text = "This section is unavailable." if language == "en" else "Cette section est indisponible."
                    return await interaction.response.send_message(text, ephemeral=True)
                pages = _category_pages(bot, prefix, language, *matching)
                home = _home_embed(bot, interaction.guild, prefix, is_staff, language)
                view = V3PagesView(bot, prefix, is_staff, language, author_id, pages, home)
                view.message = interaction.message
                await _edit(interaction, embed=pages[0], view=view)

            button.callback = callback
            self.add_item(button)

        search = discord.ui.Button(
            label="Search" if language == "en" else "Rechercher",
            emoji="🔎",
            style=discord.ButtonStyle.primary,
            row=2,
        )

        async def search_callback(interaction: discord.Interaction):
            if not await _guard_owner(interaction, author_id, language):
                return
            await interaction.response.send_modal(V3SearchModal(bot, prefix, is_staff, language, author_id))

        search.callback = search_callback
        self.add_item(search)

        close = discord.ui.Button(
            label="Close" if language == "en" else "Fermer",
            emoji="✕",
            style=discord.ButtonStyle.secondary,
            row=2,
        )

        async def close_callback(interaction: discord.Interaction):
            if not await _guard_owner(interaction, author_id, language):
                return
            await interaction.response.defer()
            try:
                await interaction.message.delete()
            except discord.HTTPException:
                pass

        close.callback = close_callback
        self.add_item(close)


class V3PagesView(_V3BaseView):
    def __init__(
        self,
        bot: commands.Bot,
        prefix: str,
        is_staff: bool,
        language: str,
        author_id: int,
        pages: list[discord.Embed],
        home_embed: discord.Embed,
    ):
        super().__init__(author_id=author_id, language=language)
        self.bot, self.prefix, self.is_staff = bot, prefix, is_staff
        self.pages, self.home_embed, self.index = pages, home_embed, 0
        self.add_item(V3Select(bot, prefix, is_staff, language, author_id))

        previous = discord.ui.Button(label="Précédent" if language != "en" else "Previous", emoji="◀️", style=discord.ButtonStyle.secondary, row=1)
        home = discord.ui.Button(label="Accueil" if language != "en" else "Home", emoji="🏠", style=discord.ButtonStyle.primary, row=1)
        next_button = discord.ui.Button(label="Suivant" if language != "en" else "Next", emoji="▶️", style=discord.ButtonStyle.secondary, row=1)
        search = discord.ui.Button(label="Rechercher" if language != "en" else "Search", emoji="🔎", style=discord.ButtonStyle.secondary, row=1)
        close = discord.ui.Button(label="Fermer" if language != "en" else "Close", emoji="✕", style=discord.ButtonStyle.secondary, row=1)

        def refresh() -> None:
            previous.disabled = self.index <= 0
            next_button.disabled = self.index >= len(self.pages) - 1

        async def previous_callback(interaction: discord.Interaction):
            if not await _guard_owner(interaction, author_id, language):
                return
            self.index = max(0, self.index - 1)
            refresh()
            await _edit(interaction, embed=self.pages[self.index], view=self)

        async def home_callback(interaction: discord.Interaction):
            if not await _guard_owner(interaction, author_id, language):
                return
            view = V3HomeView(bot, prefix, is_staff, language, author_id)
            view.message = interaction.message
            await _edit(interaction, embed=self.home_embed, view=view)

        async def next_callback(interaction: discord.Interaction):
            if not await _guard_owner(interaction, author_id, language):
                return
            self.index = min(len(self.pages) - 1, self.index + 1)
            refresh()
            await _edit(interaction, embed=self.pages[self.index], view=self)

        async def search_callback(interaction: discord.Interaction):
            if not await _guard_owner(interaction, author_id, language):
                return
            await interaction.response.send_modal(V3SearchModal(bot, prefix, is_staff, language, author_id))

        async def close_callback(interaction: discord.Interaction):
            if not await _guard_owner(interaction, author_id, language):
                return
            await interaction.response.defer()
            try:
                await interaction.message.delete()
            except discord.HTTPException:
                pass

        previous.callback = previous_callback
        home.callback = home_callback
        next_button.callback = next_callback
        search.callback = search_callback
        close.callback = close_callback
        self.add_item(previous)
        self.add_item(home)
        self.add_item(next_button)
        self.add_item(search)
        self.add_item(close)
        refresh()


def install(bot: commands.Bot) -> None:
    """Réaffirme V3 après les couches historiques sans empiler de wrapper."""
    try:
        from . import help_clean_style as clean, language_runtime
    except Exception:
        return

    help_command = bot.get_command("help")
    if help_command is None:
        return

    # Les callbacks V8 résolvent ces symboles au moment de l'exécution : remplacer leurs
    # références suffit, sans recréer /help et sans augmenter le registre de commandes.
    clean._help_home = _home_embed
    clean._category_pages = _category_pages
    clean._all_pages = _all_pages
    clean.CleanHelpSearchModal = V3SearchModal
    clean.CleanHelpSelect = V3Select
    clean.CleanHelpHomeView = V3HomeView
    clean.CleanHelpPagesView = V3PagesView

    language_runtime.LanguageHelpSelect = V3Select
    language_runtime.LanguageHelpHomeView = V3HomeView
    language_runtime.LanguageHelpPagesView = V3PagesView

    help_command.callback = clean._clean_help_callback
    help_command._sentrix_v3_ux = True
    bot._sentrix_v3_ux = True
    logger.info("SentriX V3 UX actif : aide unifiée, raccourcis, recherche et navigation premium.")


__all__ = ["install", "V3HomeView", "V3PagesView", "V3Select", "V3SearchModal"]
