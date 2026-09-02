"""SentriX V79 — catalogue d'aide complet.

Corrige le principal défaut du Help V77/V78 : la liste était construite uniquement depuis
les commandes préfixées, puis elle affichait séparément un compteur slash. Une commande
slash sans équivalent + n'apparaissait donc jamais dans les catégories.

V79 construit un catalogue unifié à partir de :
- toutes les commandes préfixées enregistrées, y compris celles marquées hidden ;
- toutes les commandes slash chat-input finales, y compris les sous-commandes de groupes.

Les commandes qui existent en + et / sont fusionnées sur une seule fiche. Les commandes
slash-only restent visibles et recherchables. Un bouton « Toutes les commandes » permet de
parcourir le catalogue complet, page par page.
"""
from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass

import discord
from discord import app_commands
from discord.ext import commands

from utils import embeds
from utils import sentrix_panels as panels
from utils.command_permissions import (
    ADMIN_COGS,
    COMMAND_PERMISSION_FALLBACKS,
    OWNER_COGS,
    command_example,
    command_requirement,
    permission_label,
)
from . import help as legacy
from . import help_components_v77 as v77
from . import setup_components_v73 as setup_v73

logger = logging.getLogger("bot.help-complete-v79")
RUNTIME_MARKER = "Help Complete Catalog V79"
HOME_PAGE_SIZE = 6
LIST_PAGE_SIZE = 6


@dataclass
class HelpEntry:
    key: str
    category: str
    prefix_command: commands.Command | None = None
    slash_name: str | None = None
    slash_command: app_commands.Command | None = None

    @property
    def name(self) -> str:
        if self.prefix_command is not None:
            return self.prefix_command.qualified_name
        return self.slash_name or self.key


def _normalise(value: str) -> str:
    return " ".join(str(value or "").strip().casefold().lstrip("+/").split())


def _binding_name(node) -> str:
    binding = getattr(node, "binding", None)
    if binding is None:
        callback = getattr(node, "callback", None)
        binding = getattr(callback, "__self__", None)
    return str(getattr(binding, "qualified_name", "") or getattr(binding, "__class__", type(None)).__name__ or "")


def _category_from_name(cog_name: str, invocation: str) -> str:
    if cog_name in v77.COG_CATEGORY:
        return v77.COG_CATEGORY[cog_name]

    folded = f"{cog_name} {invocation}".casefold()
    if any(word in folded for word in ("moder", "warn", "mute", "kick", "ban", "clear", "purge")):
        return "moderation"
    if any(word in folded for word in ("security", "secur", "automod", "anti", "verification", "verify", "antinuke")):
        return "security"
    if "ticket" in folded or "support" in folded:
        return "tickets"
    if any(word in folded for word in ("welcome", "bienvenue", "role", "autorole", "reactionrole", "community")):
        return "community"
    if "log" in folded:
        return "logs"
    if any(word in folded for word in ("econom", "balance", "bank", "money", "level", "xp", "shop")):
        return "economy"
    if any(word in folded for word in (" ai", "ia", "image", "ask", "memory", "model")):
        return "ai"
    if any(word in folded for word in ("notif", "youtube", "tiktok", "twitch")):
        return "notifications"
    if any(word in folded for word in ("game", "event", "giveaway", "minigame", "guess", "coinflip")):
        return "games"
    if any(word in folded for word in ("music", "play", "queue", "skip", "volume")):
        return "music"
    if any(word in folded for word in ("server", "member", "user", "avatar", "ping", "stats", "invite", "info", "afk")):
        return "utility"
    return "administration"


def _walk_slash(bot: commands.Bot):
    """Retourne uniquement les commandes chat-input réellement invocables."""
    def walk(node, parent: str = ""):
        name = f"{parent} {node.name}".strip()
        children = list(getattr(node, "commands", ()) or ())
        if children:
            for child in children:
                yield from walk(child, name)
            return
        yield name, node

    for node in bot.tree.get_commands(type=discord.AppCommandType.chat_input):
        yield from walk(node)


def _catalog(bot: commands.Bot) -> list[HelpEntry]:
    entries: dict[str, HelpEntry] = {}

    # Ne pas filtrer command.hidden : l'utilisateur a demandé que toutes les commandes
    # réellement enregistrées restent consultables, y compris les commandes admin/owner.
    for command in bot.walk_commands():
        name = command.qualified_name.strip()
        key = _normalise(name)
        if not key:
            continue
        category = v77._category_key(command)
        entries[key] = HelpEntry(
            key=key,
            category=category,
            prefix_command=command,
        )

    for slash_name, slash_command in _walk_slash(bot):
        key = _normalise(slash_name)
        if not key:
            continue
        entry = entries.get(key)
        if entry is None:
            entry = HelpEntry(
                key=key,
                category=_category_from_name(_binding_name(slash_command), slash_name),
            )
            entries[key] = entry
        entry.slash_name = slash_name
        entry.slash_command = slash_command

    return sorted(entries.values(), key=lambda row: row.name.casefold())


def _grouped(bot: commands.Bot) -> OrderedDict[str, list[HelpEntry]]:
    buckets: dict[str, list[HelpEntry]] = {}
    for entry in _catalog(bot):
        buckets.setdefault(entry.category, []).append(entry)

    result: OrderedDict[str, list[HelpEntry]] = OrderedDict()
    for key in v77.CATEGORY_META:
        rows = buckets.pop(key, [])
        if rows:
            result[key] = rows
    for key in sorted(buckets):
        result[key] = buckets[key]
    return result


def _description(entry: HelpEntry) -> str:
    if entry.prefix_command is not None:
        return legacy._description(entry.prefix_command)
    text = str(getattr(entry.slash_command, "description", "") or "Aucune description.").strip()
    return text.split("\n", 1)[0][:220]


def _permission(entry: HelpEntry) -> str:
    if entry.prefix_command is not None:
        return command_requirement(entry.prefix_command)

    command = entry.slash_command
    cog_name = _binding_name(command)
    if cog_name in OWNER_COGS:
        return "Propriétaire global SentriX"

    root = _normalise(entry.slash_name or entry.key).split()[0]
    fallback = COMMAND_PERMISSION_FALLBACKS.get(root)
    if fallback:
        return permission_label(fallback)
    if cog_name in ADMIN_COGS:
        return "Administrateur"

    permissions = getattr(command, "default_permissions", None)
    if permissions is not None:
        labels = [permission_label(name) for name, enabled in permissions if enabled]
        if labels:
            return ", ".join(labels[:6])
    return "Aucune permission spéciale"


def _title(entry: HelpEntry, prefix: str = "+") -> str:
    parts: list[str] = []
    if entry.slash_name:
        parts.append(f"/{entry.slash_name}")
    if entry.prefix_command is not None:
        parts.append(f"{prefix}{entry.prefix_command.qualified_name}")
    return " · ".join(parts) or entry.name


def _slash_usage(entry: HelpEntry) -> str | None:
    if not entry.slash_name:
        return None
    command = entry.slash_command
    parameters = list(getattr(command, "parameters", ()) or ())
    suffix: list[str] = []
    for parameter in parameters[:8]:
        name = str(getattr(parameter, "display_name", None) or getattr(parameter, "name", "option"))
        required = bool(getattr(parameter, "required", False))
        suffix.append(f"<{name}>" if required else f"[{name}]")
    text = f"/{entry.slash_name}"
    if suffix:
        text += " " + " ".join(suffix)
    return text


def _prefix_usage(entry: HelpEntry, prefix: str) -> str | None:
    if entry.prefix_command is None:
        return None
    return legacy._usage(entry.prefix_command, prefix)


def _example(entry: HelpEntry, prefix: str) -> str:
    if entry.prefix_command is not None:
        return command_example(entry.prefix_command, prefix)
    return _slash_usage(entry) or f"/{entry.slash_name or entry.name}"


def _aliases(entry: HelpEntry) -> str:
    command = entry.prefix_command
    if command is None or not command.aliases:
        return "Aucun"
    return ", ".join(f"`{alias}`" for alias in command.aliases[:12])


def _search(bot: commands.Bot, query: str) -> list[HelpEntry]:
    needle = _normalise(query)
    if not needle:
        return []
    ranked: list[tuple[int, HelpEntry]] = []
    for entry in _catalog(bot):
        names = [entry.key]
        if entry.slash_name:
            names.append(_normalise(entry.slash_name))
        if entry.prefix_command is not None:
            names.extend(_normalise(alias) for alias in (entry.prefix_command.aliases or []))
        category_label = v77._meta(entry.category)[1].casefold()
        description = _description(entry).casefold()
        haystack = " ".join([*names, category_label, description])
        if needle not in haystack:
            continue
        if needle in names:
            rank = 0
        elif any(name.startswith(needle) for name in names):
            rank = 1
        elif any(needle in name for name in names):
            rank = 2
        elif needle in category_label:
            rank = 3
        else:
            rank = 4
        ranked.append((rank, entry))
    ranked.sort(key=lambda item: (item[0], item[1].name.casefold()))
    return [entry for _rank, entry in ranked]


def _exact(rows: list[HelpEntry], query: str) -> HelpEntry | None:
    needle = _normalise(query)
    for entry in rows:
        names = {entry.key}
        if entry.slash_name:
            names.add(_normalise(entry.slash_name))
        if entry.prefix_command is not None:
            names.update(_normalise(alias) for alias in (entry.prefix_command.aliases or []))
        if needle in names:
            return entry
    return None


def _chunks(rows: list[HelpEntry]) -> list[list[HelpEntry]]:
    return [rows[index:index + LIST_PAGE_SIZE] for index in range(0, len(rows), LIST_PAGE_SIZE)] or [[]]


async def _private_error(interaction: discord.Interaction, text: str) -> None:
    panel = embeds.error(text)
    if interaction.response.is_done():
        await panels.envoyer(interaction.followup, panels.depuis_embed(panel), ephemere=True)
    else:
        await panels.envoyer(interaction.response, panels.depuis_embed(panel), ephemere=True)


class SearchModalV79(discord.ui.Modal, title="Rechercher une commande"):
    query = discord.ui.TextInput(
        label="Nom ou mot-clé",
        placeholder="ban, ticket, setup, image, logs...",
        min_length=1,
        max_length=60,
    )

    def __init__(self, view: "SentriXHelpV79"):
        super().__init__(timeout=300)
        self.help_view = view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        query = str(self.query.value).strip()
        rows = _search(self.help_view.bot, query)
        exact = _exact(rows, query)
        if exact is not None:
            self.help_view.show_detail(exact)
        else:
            self.help_view.show_search(query, rows)
        if not interaction.response.is_done():
            await interaction.response.defer()
        await self.help_view._edit(interaction)


class SentriXHelpV79(discord.ui.LayoutView):
    def __init__(self, bot: commands.Bot, prefix: str, author_id: int, *, member=None):
        super().__init__(timeout=900)
        self.bot = bot
        self.prefix = prefix
        self.author_id = int(author_id)
        self.member = member or bot.get_user(author_id)
        self.mode = "home"
        self.category_key: str | None = None
        self.rows: list[HelpEntry] = []
        self.index = 0
        self.home_index = 0
        self.query: str | None = None
        self.entry: HelpEntry | None = None
        self.return_mode = "home"
        self.return_category: str | None = None
        self.return_rows: list[HelpEntry] = []
        self.return_index = 0
        self.return_query: str | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if int(interaction.user.id) == self.author_id:
            return True
        await _private_error(interaction, "Ce panneau d'aide appartient à une autre personne.")
        return False

    async def prepare(self) -> None:
        self.rebuild()

    def show_home(self) -> None:
        self.mode = "home"
        self.category_key = None
        self.rows = []
        self.index = 0
        self.query = None
        self.entry = None

    def show_all(self) -> None:
        self.mode = "all"
        self.category_key = None
        self.rows = _catalog(self.bot)
        self.index = 0
        self.query = None
        self.entry = None

    def show_category(self, key: str) -> None:
        self.mode = "category"
        self.category_key = key
        self.rows = list(_grouped(self.bot).get(key, []))
        self.index = 0
        self.query = None
        self.entry = None

    def show_search(self, query: str, rows: list[HelpEntry] | None = None) -> None:
        self.mode = "search"
        self.category_key = None
        self.query = query.strip()
        self.rows = list(rows if rows is not None else _search(self.bot, query))
        self.index = 0
        self.entry = None

    def show_detail(self, entry: HelpEntry) -> None:
        self.return_mode = self.mode
        self.return_category = self.category_key
        self.return_rows = list(self.rows)
        self.return_index = self.index
        self.return_query = self.query
        self.mode = "detail"
        self.entry = entry

    def go_back_from_detail(self) -> None:
        self.mode = self.return_mode
        self.category_key = self.return_category
        self.rows = list(self.return_rows)
        self.index = self.return_index
        self.query = self.return_query
        self.entry = None
        if self.mode not in {"category", "search", "all"}:
            self.show_home()

    async def refresh(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer()
        await self._edit(interaction)

    async def _edit(self, interaction: discord.Interaction) -> None:
        self.rebuild()
        await interaction.edit_original_response(content=None, embed=None, attachments=[], view=self)

    def rebuild(self) -> None:
        self.clear_items()
        if self.mode in {"category", "search", "all"}:
            self._build_list()
        elif self.mode == "detail":
            self._build_detail()
        elif self.mode == "closed":
            self.add_item(
                discord.ui.Container(
                    discord.ui.TextDisplay("# Aide fermée\nRelancez `+help` ou `/help` pour rouvrir le centre d'aide."),
                    accent_colour=setup_v73.ACCENT,
                )
            )
        else:
            self._build_home()

    def _build_home(self) -> None:
        entries = _catalog(self.bot)
        grouped = _grouped(self.bot)
        prefix_count = sum(entry.prefix_command is not None for entry in entries)
        slash_count = sum(entry.slash_name is not None for entry in entries)
        slash_only = sum(entry.slash_name is not None and entry.prefix_command is None for entry in entries)

        keys = list(grouped.keys())
        pages = max(1, (len(keys) + HOME_PAGE_SIZE - 1) // HOME_PAGE_SIZE)
        self.home_index = min(max(self.home_index, 0), pages - 1)
        start = self.home_index * HOME_PAGE_SIZE
        page_keys = keys[start:start + HOME_PAGE_SIZE]

        container = discord.ui.Container(accent_colour=setup_v73.ACCENT)
        container.add_item(
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "# Centre d'aide SentriX\n"
                    "Le catalogue affiche maintenant **toutes les commandes enregistrées** : commandes `+`, commandes `/`, "
                    "sous-commandes slash et commandes administratives.\n\n"
                    f"**{len(entries)} commandes uniques** · **{prefix_count} en +** · **{slash_count} en /**"
                    + (f" · **{slash_only} uniquement en /**" if slash_only else "")
                    + f"\nCatégories : page **{self.home_index + 1}/{pages}**"
                ),
                accessory=setup_v73._thumbnail(self.bot),
            )
        )
        container.add_item(discord.ui.Separator())

        for index, key in enumerate(page_keys):
            emoji, label, description = v77._meta(key)
            rows = grouped[key]
            button = discord.ui.Button(label="Voir les commandes", style=discord.ButtonStyle.secondary)

            async def open_category(interaction: discord.Interaction, category_key=key):
                self.show_category(category_key)
                await self.refresh(interaction)

            button.callback = open_category
            container.add_item(
                discord.ui.Section(
                    discord.ui.TextDisplay(f"## {emoji} {label}\n{description}\n**{len(rows)} commande(s)**"),
                    accessory=button,
                )
            )
            if index == 2 and len(page_keys) > 3:
                container.add_item(discord.ui.Separator())

        previous = discord.ui.Button(label="Précédent", style=discord.ButtonStyle.secondary, disabled=self.home_index <= 0)
        all_commands = discord.ui.Button(label="Toutes les commandes", style=discord.ButtonStyle.primary)
        search = discord.ui.Button(label="Rechercher", style=discord.ButtonStyle.secondary, emoji="🔎")
        next_button = discord.ui.Button(label="Suivant", style=discord.ButtonStyle.secondary, disabled=self.home_index >= pages - 1)
        close = discord.ui.Button(label="Fermer", style=discord.ButtonStyle.danger)

        async def go_previous(interaction: discord.Interaction):
            self.home_index = max(0, self.home_index - 1)
            await self.refresh(interaction)

        async def open_all(interaction: discord.Interaction):
            self.show_all()
            await self.refresh(interaction)

        async def open_search(interaction: discord.Interaction):
            await interaction.response.send_modal(SearchModalV79(self))

        async def go_next(interaction: discord.Interaction):
            self.home_index = min(pages - 1, self.home_index + 1)
            await self.refresh(interaction)

        async def close_help(interaction: discord.Interaction):
            self.mode = "closed"
            await self.refresh(interaction)
            self.stop()

        previous.callback = go_previous
        all_commands.callback = open_all
        search.callback = open_search
        next_button.callback = go_next
        close.callback = close_help
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.ActionRow(previous, all_commands, search, next_button, close))
        self.add_item(container)

    def _build_list(self) -> None:
        if self.mode == "category" and self.category_key:
            emoji, label, description = v77._meta(self.category_key)
            title = f"{emoji} {label}"
            subtitle = description
        elif self.mode == "all":
            title = "📚 Toutes les commandes"
            subtitle = "Catalogue complet des commandes `+` et `/` enregistrées dans SentriX."
        else:
            title = "🔎 Recherche"
            subtitle = f"Résultats pour **{self.query or ''}**"

        pages = _chunks(self.rows)
        self.index = min(max(self.index, 0), len(pages) - 1)
        chunk = pages[self.index]
        container = discord.ui.Container(accent_colour=setup_v73.ACCENT)
        container.add_item(
            discord.ui.Section(
                discord.ui.TextDisplay(
                    f"# {title}\n{subtitle}\n**{len(self.rows)} commande(s)** · page **{self.index + 1}/{len(pages)}**"
                ),
                accessory=setup_v73._thumbnail(self.bot),
            )
        )
        container.add_item(discord.ui.Separator())

        if not chunk:
            container.add_item(discord.ui.TextDisplay("### Aucun résultat\nAucune commande ne correspond à cette recherche."))
        else:
            for entry in chunk:
                detail = discord.ui.Button(label="Détails", style=discord.ButtonStyle.secondary)

                async def open_detail(interaction: discord.Interaction, selected=entry):
                    self.show_detail(selected)
                    await self.refresh(interaction)

                detail.callback = open_detail
                container.add_item(
                    discord.ui.Section(
                        discord.ui.TextDisplay(
                            f"### {_title(entry, self.prefix)}\n{_description(entry)}\n**Permission :** {_permission(entry)}"
                        ),
                        accessory=detail,
                    )
                )

        home = discord.ui.Button(label="Accueil", style=discord.ButtonStyle.primary, emoji="↩️")
        previous = discord.ui.Button(label="Précédent", style=discord.ButtonStyle.secondary, disabled=self.index <= 0)
        next_button = discord.ui.Button(label="Suivant", style=discord.ButtonStyle.secondary, disabled=self.index >= len(pages) - 1)
        search = discord.ui.Button(label="Rechercher", style=discord.ButtonStyle.secondary, emoji="🔎")
        close = discord.ui.Button(label="Fermer", style=discord.ButtonStyle.danger)

        async def go_home(interaction: discord.Interaction):
            self.show_home()
            await self.refresh(interaction)

        async def go_previous(interaction: discord.Interaction):
            self.index = max(0, self.index - 1)
            await self.refresh(interaction)

        async def go_next(interaction: discord.Interaction):
            self.index = min(len(pages) - 1, self.index + 1)
            await self.refresh(interaction)

        async def open_search(interaction: discord.Interaction):
            await interaction.response.send_modal(SearchModalV79(self))

        async def close_help(interaction: discord.Interaction):
            self.mode = "closed"
            await self.refresh(interaction)
            self.stop()

        home.callback = go_home
        previous.callback = go_previous
        next_button.callback = go_next
        search.callback = open_search
        close.callback = close_help
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.ActionRow(home, previous, next_button, search, close))
        self.add_item(container)

    def _build_detail(self) -> None:
        entry = self.entry
        if entry is None:
            self.show_home()
            return self._build_home()

        emoji, category_label, _ = v77._meta(entry.category)
        usage_lines: list[str] = []
        slash_usage = _slash_usage(entry)
        prefix_usage = _prefix_usage(entry, self.prefix)
        if slash_usage:
            usage_lines.append(f"`{slash_usage}`")
        if prefix_usage:
            usage_lines.append(f"`{prefix_usage}`")

        container = discord.ui.Container(accent_colour=setup_v73.ACCENT)
        container.add_item(
            discord.ui.Section(
                discord.ui.TextDisplay(f"# {_title(entry, self.prefix)}\n{_description(entry)}"),
                accessory=setup_v73._thumbnail(self.bot),
            )
        )
        container.add_item(discord.ui.Separator())
        container.add_item(
            discord.ui.TextDisplay(
                "### Utilisation\n"
                + ("\n".join(usage_lines) if usage_lines else "Aucune syntaxe disponible.")
                + f"\n\n### Permission nécessaire\n{_permission(entry)}"
                + f"\n\n### Catégorie\n{emoji} {category_label}"
                + f"\n\n### Exemple\n`{_example(entry, self.prefix)}`"
                + f"\n\n### Alias\n{_aliases(entry)}"
            )
        )

        back = discord.ui.Button(label="Retour", style=discord.ButtonStyle.primary, emoji="↩️")
        home = discord.ui.Button(label="Accueil", style=discord.ButtonStyle.secondary)
        search = discord.ui.Button(label="Rechercher", style=discord.ButtonStyle.secondary, emoji="🔎")
        close = discord.ui.Button(label="Fermer", style=discord.ButtonStyle.danger)

        async def go_back(interaction: discord.Interaction):
            self.go_back_from_detail()
            await self.refresh(interaction)

        async def go_home(interaction: discord.Interaction):
            self.show_home()
            await self.refresh(interaction)

        async def open_search(interaction: discord.Interaction):
            await interaction.response.send_modal(SearchModalV79(self))

        async def close_help(interaction: discord.Interaction):
            self.mode = "closed"
            await self.refresh(interaction)
            self.stop()

        back.callback = go_back
        home.callback = go_home
        search.callback = open_search
        close.callback = close_help
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.ActionRow(back, home, search, close))
        self.add_item(container)

    async def on_error(self, interaction: discord.Interaction, error: Exception, item=None) -> None:
        logger.error("Erreur Help V79", exc_info=(type(error), error, error.__traceback__))
        try:
            await _private_error(interaction, "Une erreur est survenue dans le centre d'aide SentriX.")
        except discord.HTTPException:
            pass


async def _send_help_v79(self, target, query: str | None = None):
    member = getattr(target, "author", None) or getattr(target, "user", None)
    if member is None:
        return
    view = SentriXHelpV79(self.bot, "+", member.id, member=member)
    if query:
        rows = _search(self.bot, query)
        exact = _exact(rows, query)
        if exact is not None:
            view.show_detail(exact)
        else:
            view.show_search(query, rows)
    await view.prepare()

    if isinstance(target, commands.Context):
        return await target.send(content=None, embed=None, view=view)
    if target.response.is_done():
        return await target.followup.send(content=None, embed=None, view=view)
    return await target.response.send_message(content=None, embed=None, view=view)


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_help_complete_v79", False):
        return
    if not hasattr(discord.ui, "LayoutView"):
        raise RuntimeError("SentriX Help V79 exige discord.py 2.6+.")

    current = legacy.OfficialHelp.send_help
    if not getattr(current, "_sentrix_help_complete_v79", False):
        _send_help_v79._sentrix_help_complete_v79 = True
        _send_help_v79._sentrix_previous = current
        legacy.OfficialHelp.send_help = _send_help_v79

    bot._sentrix_help_complete_v79 = True
    logger.info(
        "%s installé : +help et /help listent désormais toutes les commandes + et /, y compris slash-only.",
        RUNTIME_MARKER,
    )


__all__ = ["HelpEntry", "SentriXHelpV79", "_catalog", "install"]
