"""Final command surface requested for SentriX.

This layer runs after the historical V3/V41 polish so older renderers cannot put
embeds/emojis back on +help and the slash budget cannot hide useful legacy slash
commands again.
"""
from __future__ import annotations

import inspect
import logging
import re
from collections import OrderedDict
from dataclasses import dataclass

import discord
from discord import app_commands
from discord.ext import commands
from discord.ext.commands.hybrid import HybridAppCommand

logger = logging.getLogger("bot.command-surface-user-final")

_MAX_SLASH = 100
_ALL = "__sentrix_plain_all__"
_CUSTOM_EMOJI_RE = re.compile(r"<a?:[A-Za-z0-9_]{2,32}:\d+>")


def _clean_text(value: object, limit: int = 180) -> str:
    text = _CUSTOM_EMOJI_RE.sub("", str(value or ""))
    chars: list[str] = []
    for char in text:
        code = ord(char)
        if (
            0x1F000 <= code <= 0x1FAFF
            or 0x2600 <= code <= 0x27BF
            or code in {0xFE0F, 0x200D}
        ):
            continue
        chars.append(char)
    text = re.sub(r"\s+", " ", "".join(chars)).strip(" -•·|")
    if len(text) > limit:
        text = text[: max(0, limit - 1)].rstrip() + "…"
    return text


def _global_roots(bot: commands.Bot) -> list[app_commands.Command | app_commands.Group]:
    try:
        return list(
            bot.tree.get_commands(
                guild=None,
                type=discord.AppCommandType.chat_input,
            )
        )
    except Exception:
        return [
            item
            for item in bot.tree.get_commands(guild=None)
            if isinstance(item, (app_commands.Command, app_commands.Group))
        ]


def _remove_global_root(bot: commands.Bot, name: str) -> None:
    try:
        bot.tree.remove_command(name, type=discord.AppCommandType.chat_input)
    except TypeError:
        bot.tree.remove_command(name)


def _hard_excluded_names() -> set[str]:
    from . import command_catalog_cleanup as catalog

    # Tickets intentionally keep one public slash root: /ticket. The ticket group
    # contains its own useful actions without spending extra global roots.
    return (
        set(catalog.PURE_DUPLICATE_COMMANDS)
        | set(catalog.TICKET_MERGED_COMMANDS)
    )


def _low_priority_names() -> set[str]:
    from . import command_catalog_cleanup as catalog

    return set(catalog.LOW_VALUE_HIDDEN_COMMANDS)


def _restore_slash_surface(bot: commands.Bot) -> None:
    """Keep native/legacy slash first; fill remaining slots from useful + hybrids."""
    from . import command_catalog_cleanup as catalog
    from . import slash_command_budget as budget

    hard_excluded = _hard_excluded_names()
    low_priority = _low_priority_names()

    # The old budget excluded whole admin/setup/security families. From this point on,
    # only true duplicates and redundant ticket roots are hard-excluded.
    budget._excluded_names = lambda: set(hard_excluded)

    saved_roots = {
        str(getattr(item, "name", "") or "").casefold(): item
        for item in _global_roots(bot)
        if str(getattr(item, "name", "") or "").strip()
    }

    hybrid_by_app_name: dict[str, commands.HybridCommand] = {}
    native_names: list[str] = []
    plus_names: list[str] = []
    prefix_fallback_names: list[str] = []

    for command in list(bot.commands):
        if command.parent is not None or not isinstance(command, commands.HybridCommand):
            continue
        command_name = str(getattr(command, "name", "") or "").casefold()
        if not command_name or command_name in hard_excluded:
            continue

        app = getattr(command, "app_command", None)
        app_name = str(getattr(app, "name", "") or command_name).casefold()
        hybrid_by_app_name.setdefault(app_name, command)

        if app is not None and not getattr(command, "_sentrix_slash_from_plus", False):
            native_names.append(app_name)
        elif getattr(command, "_sentrix_slash_from_plus", False):
            plus_names.append(app_name)
        else:
            prefix_fallback_names.append(app_name)

    # Non-hybrid application commands that already exist are native slash commands too.
    native_names.extend(saved_roots)

    # Core roots are kept at the very front if they exist.
    mandatory = ("help", "ticket", "setup")

    # Low-value diagnostics remain possible only if there is spare room after the useful
    # legacy slash and the useful + fallbacks.
    normal_plus = [
        name
        for name in plus_names
        if name not in low_priority
    ]
    fallback_plus = [
        name
        for name in prefix_fallback_names
        if name not in low_priority
    ]
    low = [
        name
        for name in [*plus_names, *prefix_fallback_names, *native_names]
        if name in low_priority
    ]

    ordered: list[str] = []
    seen: set[str] = set()

    def add_names(values) -> None:
        for raw in values:
            name = str(raw or "").casefold()
            if not name or name in hard_excluded or name in seen:
                continue
            seen.add(name)
            ordered.append(name)

    add_names(mandatory)
    add_names([name for name in native_names if name not in low_priority])

    # Prefix commands are only converted to slash after all native/legacy slash roots.
    # Within that spare-space phase, keep the curated direct commands before obscure
    # hidden commands.
    curated_plus = [
        ("nick" if name == "nickname" else name)
        for name in catalog.NORMAL_DIRECT_COMMANDS
        if name not in catalog.LOW_VALUE_HIDDEN_COMMANDS
    ]
    add_names(curated_plus)
    add_names(normal_plus)
    add_names(fallback_plus)
    add_names(low)

    # Rebuild deterministically. This avoids the old "first 100 loaded wins" behaviour
    # and makes the priority above the actual source of truth.
    for item in list(_global_roots(bot)):
        name = str(getattr(item, "name", "") or "").casefold()
        if name:
            _remove_global_root(bot, name)

    selected: set[str] = set()
    budget._preferred_names = lambda: set(selected) | set(ordered[:_MAX_SLASH])

    for name in ordered:
        if len(_global_roots(bot)) >= _MAX_SLASH:
            break

        app = saved_roots.get(name)
        if app is None:
            command = hybrid_by_app_name.get(name)
            if command is None and name == "nick":
                command = bot.get_command("nickname") or bot.get_command("nick")
            if command is None:
                command = bot.get_command(name)
            if not isinstance(command, commands.HybridCommand):
                continue
            try:
                app = command.app_command
                if app is None:
                    command.with_app_command = True
                    app = HybridAppCommand(command)
                    command.app_command = app
                    command._sentrix_slash_from_plus = True
            except (TypeError, ValueError):
                logger.debug("Slash non représentable pour +%s.", name, exc_info=True)
                continue

        app_name = str(getattr(app, "name", "") or name).casefold()
        if app_name in hard_excluded or app_name in selected:
            continue
        try:
            bot.tree.add_command(app, override=True)
            if bot.tree.get_command(app_name) is not None:
                selected.add(app_name)
        except (TypeError, ValueError):
            logger.debug("Impossible de restaurer /%s.", app_name, exc_info=True)

    # Keep the runtime budget aligned with this final policy for any late registration.
    budget._preferred_names = lambda: set(selected)
    budget.finalize(bot)
    bot._sentrix_final_slash_names = frozenset(selected)
    logger.info(
        "Surface slash finale : %s/%s racines, anciennes / prioritaires, + en remplissage.",
        len(_global_roots(bot)),
        _MAX_SLASH,
    )


@dataclass(frozen=True)
class _Entry:
    name: str
    display: str
    description: str
    category_key: str
    category_name: str
    slash: bool


def _category_for_prefix(command: commands.Command | None):
    from . import help_complete

    if command is None:
        return help_complete.CATEGORY_BY_KEY["other"]
    try:
        return help_complete._category_for(command)
    except Exception:
        return help_complete.CATEGORY_BY_KEY["other"]


def _prefix_command_for_slash(bot: commands.Bot, name: str) -> commands.Command | None:
    command = bot.get_command(name)
    if command is None and name == "nick":
        command = bot.get_command("nickname")
    return command


def _entries(bot: commands.Bot, prefix: str) -> list[_Entry]:
    slash_entries: list[_Entry] = []
    slash_names: set[str] = set()

    for app in _global_roots(bot):
        name = str(getattr(app, "name", "") or "").casefold()
        if not name:
            continue
        slash_names.add(name)
        command = _prefix_command_for_slash(bot, name)
        category = _category_for_prefix(command)
        description = _clean_text(
            getattr(app, "description", "")
            or getattr(command, "description", "")
            or getattr(command, "help", "")
            or "Commande SentriX."
        )
        slash_entries.append(
            _Entry(
                name=name,
                display=f"/{name}",
                description=description,
                category_key=str(getattr(category, "key", "other")),
                category_name=_clean_text(getattr(category, "name", "Autres"), 80) or "Autres",
                slash=True,
            )
        )

    plus_entries: list[_Entry] = []
    for command in bot.commands:
        if command.parent is not None or getattr(command, "hidden", False):
            continue
        name = str(getattr(command, "name", "") or "").casefold()
        if not name or name in slash_names or name in _hard_excluded_names():
            continue
        category = _category_for_prefix(command)
        description = _clean_text(
            getattr(command, "description", "")
            or getattr(command, "help", "")
            or "Commande SentriX."
        )
        plus_entries.append(
            _Entry(
                name=name,
                display=f"{prefix}{name}",
                description=description,
                category_key=str(getattr(category, "key", "other")),
                category_name=_clean_text(getattr(category, "name", "Autres"), 80) or "Autres",
                slash=False,
            )
        )

    slash_entries.sort(key=lambda item: (item.category_name.casefold(), item.name))
    plus_entries.sort(key=lambda item: (item.category_name.casefold(), item.name))
    return [*slash_entries, *plus_entries]


def _home_text(bot: commands.Bot, prefix: str, entries: list[_Entry], language: str) -> str:
    slash_count = sum(1 for item in entries if item.slash)
    plus_count = sum(1 for item in entries if not item.slash)
    if language == "en":
        return (
            "SentriX — Commands\n\n"
            "Choose a category below or press Search.\n"
            "Slash commands are shown first; + commands only appear when they do not duplicate a slash command.\n\n"
            f"Slash: {slash_count} | Prefix {prefix}: {plus_count}"
        )
    return (
        "SentriX — Commandes\n\n"
        "Choisis une catégorie ci-dessous ou appuie sur Rechercher.\n"
        "Les commandes / passent en premier ; les commandes + ne sont affichées que si elles ne doublonnent pas une /.\n\n"
        f"Slash : {slash_count} | Préfixe {prefix} : {plus_count}"
    )


def _chunk_lines(title: str, rows: list[str], footer: str = "") -> list[str]:
    pages: list[str] = []
    current = title.strip()
    for row in rows:
        candidate = f"{current}\n{row}" if current else row
        if len(candidate) > 1750 and current != title.strip():
            pages.append(current)
            current = f"{title.strip()}\n{row}"
        else:
            current = candidate
    if not rows:
        current = f"{title.strip()}\nAucune commande."
    if footer:
        candidate = f"{current}\n\n{footer}"
        if len(candidate) <= 1900:
            current = candidate
    pages.append(current)
    return pages


def _pages_for(entries: list[_Entry], title: str, language: str) -> list[str]:
    slash = [item for item in entries if item.slash]
    plus = [item for item in entries if not item.slash]
    rows: list[str] = []
    if slash:
        rows.append("Commandes /" if language != "en" else "Slash commands")
        rows.extend(
            f"`{item.display}` — {item.description or ('Commande SentriX.' if language != 'en' else 'SentriX command.')}"
            for item in slash
        )
    if plus:
        if rows:
            rows.append("")
        rows.append("Commandes +" if language != "en" else "+ commands")
        rows.extend(
            f"`{item.display}` — {item.description or ('Commande SentriX.' if language != 'en' else 'SentriX command.')}"
            for item in plus
        )
    return _chunk_lines(title, rows)


async def _language(bot: commands.Bot, guild_id: int | None) -> str:
    try:
        from . import language_runtime
        return await language_runtime.get_language(bot, guild_id)
    except Exception:
        return "fr"


async def _guard(interaction: discord.Interaction, author_id: int, language: str) -> bool:
    if interaction.user.id == author_id:
        return True
    text = (
        "This command menu belongs to another user."
        if language == "en"
        else "Ce menu de commandes appartient à une autre personne."
    )
    if interaction.response.is_done():
        await interaction.followup.send(text, ephemeral=True)
    else:
        await interaction.response.send_message(text, ephemeral=True)
    return False


async def _edit(interaction: discord.Interaction, content: str, view: discord.ui.View) -> None:
    if not interaction.response.is_done():
        await interaction.response.edit_message(content=content, embed=None, view=view)
    elif interaction.message is not None:
        await interaction.message.edit(content=content, embed=None, view=view)


class _SearchModal(discord.ui.Modal):
    def __init__(
        self,
        bot: commands.Bot,
        prefix: str,
        language: str,
        author_id: int,
        entries: list[_Entry],
        home: str,
    ):
        super().__init__(title="Search commands" if language == "en" else "Rechercher une commande")
        self.bot = bot
        self.prefix = prefix
        self.language = language
        self.author_id = author_id
        self.entries = entries
        self.home = home
        self.query = discord.ui.TextInput(
            label="Name or keyword" if language == "en" else "Nom ou mot-clé",
            placeholder="ticket, ban, image, logs...",
            max_length=60,
        )
        self.add_item(self.query)

    async def on_submit(self, interaction: discord.Interaction):
        if not await _guard(interaction, self.author_id, self.language):
            return
        needle = _clean_text(self.query.value, 60).casefold()
        matches = [
            item
            for item in self.entries
            if needle in f"{item.name} {item.description} {item.category_name}".casefold()
        ]
        if not matches:
            text = (
                f"No command found for {self.query.value}."
                if self.language == "en"
                else f"Aucune commande trouvée pour {self.query.value}."
            )
            view = _HomeView(
                self.bot,
                self.prefix,
                self.language,
                self.author_id,
                self.entries,
                self.home,
            )
            view.message = interaction.message
            return await _edit(interaction, f"SentriX — Recherche\n\n{text}", view)

        title = (
            f"SentriX — Search: {_clean_text(self.query.value, 40)}"
            if self.language == "en"
            else f"SentriX — Recherche : {_clean_text(self.query.value, 40)}"
        )
        pages = _pages_for(matches, title, self.language)
        view = _PagesView(
            self.bot,
            self.prefix,
            self.language,
            self.author_id,
            self.entries,
            self.home,
            pages,
        )
        view.message = interaction.message
        await _edit(interaction, pages[0], view)


class _CategorySelect(discord.ui.Select):
    def __init__(
        self,
        bot: commands.Bot,
        prefix: str,
        language: str,
        author_id: int,
        entries: list[_Entry],
        home: str,
    ):
        self.bot = bot
        self.prefix = prefix
        self.language = language
        self.author_id = author_id
        self.entries = entries
        self.home = home

        grouped: OrderedDict[str, tuple[str, int]] = OrderedDict()
        for item in entries:
            if item.category_key not in grouped:
                grouped[item.category_key] = (item.category_name, 0)
            label, count = grouped[item.category_key]
            grouped[item.category_key] = (label, count + 1)

        options = [
            discord.SelectOption(
                label="All commands" if language == "en" else "Toutes les commandes",
                value=_ALL,
                description=f"{len(entries)} " + ("commands" if language == "en" else "commandes"),
            )
        ]
        for key, (label, count) in grouped.items():
            options.append(
                discord.SelectOption(
                    label=_clean_text(label, 95) or "Autres",
                    value=key,
                    description=f"{count} " + ("commands" if language == "en" else "commandes"),
                )
            )

        super().__init__(
            placeholder="Choose a category..." if language == "en" else "Choisis une catégorie...",
            options=options[:25],
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        if not await _guard(interaction, self.author_id, self.language):
            return
        value = self.values[0]
        if value == _ALL:
            subset = self.entries
            title = "SentriX — All commands" if self.language == "en" else "SentriX — Toutes les commandes"
        else:
            subset = [item for item in self.entries if item.category_key == value]
            category_name = subset[0].category_name if subset else "Autres"
            title = f"SentriX — {category_name}"

        pages = _pages_for(subset, title, self.language)
        view = _PagesView(
            self.bot,
            self.prefix,
            self.language,
            self.author_id,
            self.entries,
            self.home,
            pages,
        )
        view.message = interaction.message
        await _edit(interaction, pages[0], view)


class _BaseView(discord.ui.View):
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


class _HomeView(_BaseView):
    def __init__(
        self,
        bot: commands.Bot,
        prefix: str,
        language: str,
        author_id: int,
        entries: list[_Entry],
        home: str,
    ):
        super().__init__(author_id)
        self.bot = bot
        self.prefix = prefix
        self.language = language
        self.entries = entries
        self.home = home
        self.add_item(_CategorySelect(bot, prefix, language, author_id, entries, home))

        search = discord.ui.Button(
            label="Search" if language == "en" else "Rechercher",
            style=discord.ButtonStyle.primary,
            row=1,
        )
        close = discord.ui.Button(
            label="Close" if language == "en" else "Fermer",
            style=discord.ButtonStyle.secondary,
            row=1,
        )

        async def search_callback(interaction: discord.Interaction):
            if not await _guard(interaction, author_id, language):
                return
            await interaction.response.send_modal(
                _SearchModal(bot, prefix, language, author_id, entries, home)
            )

        async def close_callback(interaction: discord.Interaction):
            if not await _guard(interaction, author_id, language):
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


class _PagesView(_BaseView):
    def __init__(
        self,
        bot: commands.Bot,
        prefix: str,
        language: str,
        author_id: int,
        entries: list[_Entry],
        home: str,
        pages: list[str],
    ):
        super().__init__(author_id)
        self.bot = bot
        self.prefix = prefix
        self.language = language
        self.entries = entries
        self.home = home
        self.pages = pages or [home]
        self.index = 0
        self.add_item(_CategorySelect(bot, prefix, language, author_id, entries, home))

        previous = discord.ui.Button(
            label="Previous" if language == "en" else "Précédent",
            style=discord.ButtonStyle.secondary,
            row=1,
        )
        home_button = discord.ui.Button(
            label="Home" if language == "en" else "Accueil",
            style=discord.ButtonStyle.primary,
            row=1,
        )
        next_button = discord.ui.Button(
            label="Next" if language == "en" else "Suivant",
            style=discord.ButtonStyle.secondary,
            row=1,
        )
        search = discord.ui.Button(
            label="Search" if language == "en" else "Rechercher",
            style=discord.ButtonStyle.secondary,
            row=1,
        )
        close = discord.ui.Button(
            label="Close" if language == "en" else "Fermer",
            style=discord.ButtonStyle.secondary,
            row=1,
        )

        def refresh() -> None:
            previous.disabled = self.index <= 0
            next_button.disabled = self.index >= len(self.pages) - 1

        async def previous_callback(interaction: discord.Interaction):
            if not await _guard(interaction, author_id, language):
                return
            self.index = max(0, self.index - 1)
            refresh()
            await _edit(interaction, self.pages[self.index], self)

        async def next_callback(interaction: discord.Interaction):
            if not await _guard(interaction, author_id, language):
                return
            self.index = min(len(self.pages) - 1, self.index + 1)
            refresh()
            await _edit(interaction, self.pages[self.index], self)

        async def home_callback(interaction: discord.Interaction):
            if not await _guard(interaction, author_id, language):
                return
            view = _HomeView(bot, prefix, language, author_id, entries, home)
            view.message = interaction.message
            await _edit(interaction, home, view)

        async def search_callback(interaction: discord.Interaction):
            if not await _guard(interaction, author_id, language):
                return
            await interaction.response.send_modal(
                _SearchModal(bot, prefix, language, author_id, entries, home)
            )

        async def close_callback(interaction: discord.Interaction):
            if not await _guard(interaction, author_id, language):
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


def _install_plain_help(bot: commands.Bot) -> None:
    command = bot.get_command("help")
    if command is None:
        return

    async def plain_help_callback(*args, **kwargs):
        del kwargs
        ctx = next((value for value in args if isinstance(value, commands.Context)), None)
        if ctx is None:
            raise TypeError("Context Discord introuvable pour +help")

        active_bot = ctx.bot
        prefix = str(getattr(ctx, "clean_prefix", None) or "+")
        if ctx.guild is not None:
            cached = getattr(active_bot, "prefix_cache", {}).get(ctx.guild.id)
            if cached:
                prefix = str(cached)

        language = await _language(active_bot, ctx.guild.id if ctx.guild else None)
        entries = _entries(active_bot, prefix)
        home = _home_text(active_bot, prefix, entries, language)
        view = _HomeView(active_bot, prefix, language, ctx.author.id, entries, home)
        message = await ctx.send(content=home, embed=None, view=view)
        view.message = message
        return message

    plain_help_callback.__name__ = "help_cmd"
    plain_help_callback._sentrix_plain_help_final = True
    command.callback = plain_help_callback
    command.params = OrderedDict()
    command.usage = ""
    command.description = "Afficher les commandes SentriX sans embed."
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

    bot._sentrix_plain_help_final = True
    logger.info("Aide finale SentriX : texte simple, sans embed ni emoji, recherche active.")


def install(bot: commands.Bot) -> None:
    _restore_slash_surface(bot)
    _install_plain_help(bot)
