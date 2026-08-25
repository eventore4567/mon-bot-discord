"""Aide officielle SentriX, basée sur le registre réel des commandes.

Ce cog retire l'ancien +help de Utility et possède seul +help et /help.
"""
from __future__ import annotations

import os
from collections import OrderedDict

import discord
from discord import app_commands
from discord.ext import commands

from utils import embeds

# 8 commandes gardent les pages suffisamment courtes pour que la navigation reste
# accessible sur mobile tout en respectant la cible demandée (8 à 12 commandes/page).
PAGE_SIZE = 8

CATEGORY_NAMES = {
    "Ai": "Intelligence artificielle",
    "Economy": "Économie et boutique",
    "Levels": "Niveaux et communauté",
    "Minigames": "Mini-jeux",
    "GamesEconomy": "Mini-jeux",
    "Music": "Musique",
    "Events": "Événements",
    "Invites": "Invitations",
    "Utility": "Utilitaires",
    "Notifications": "Notifications",
    "Moderation": "Modération",
    "Automod": "Sécurité",
    "Security": "Sécurité",
    "Tickets": "Tickets",
    "Verification": "Vérification et rôles",
    "Configuration": "Configuration et logs",
    "Logs": "Configuration et logs",
    "ServerBuilder": "Création de serveur",
    "Stats": "Statistiques",
    "Owner": "Propriétaire",
    "EmbedBuilder": "Créateur d'embeds",
    "Design": "Design et apparence",
}

CATEGORY_ORDER = [
    "Essentiels",
    "Intelligence artificielle",
    "Économie et boutique",
    "Niveaux et communauté",
    "Mini-jeux",
    "Musique",
    "Événements",
    "Invitations",
    "Utilitaires",
    "Notifications",
    "Modération",
    "Sécurité",
    "Tickets",
    "Vérification et rôles",
    "Configuration et logs",
    "Création de serveur",
    "Statistiques",
    "Créateur d'embeds",
    "Design et apparence",
    "Propriétaire",
]

STAFF_COGS = {
    "Moderation", "Automod", "Security", "Configuration", "Logs",
    "ServerBuilder", "Verification", "Owner", "EmbedBuilder",
}


def _is_staff(member: discord.Member | discord.User | None) -> bool:
    return isinstance(member, discord.Member) and (
        member.guild_permissions.administrator
        or member.guild_permissions.manage_guild
        or member.guild_permissions.moderate_members
    )


def _cog_name(command: commands.Command) -> str:
    return getattr(command.cog, "qualified_name", "Utility") if command.cog else "Utility"


def _category(command: commands.Command) -> str:
    return CATEGORY_NAMES.get(_cog_name(command), _cog_name(command))


def _visible(bot: commands.Bot, member) -> list[commands.Command]:
    staff = _is_staff(member)
    rows: list[commands.Command] = []
    seen: set[str] = set()
    for command in bot.walk_commands():
        if command.hidden:
            continue
        if not staff and _cog_name(command) in STAFF_COGS:
            continue
        key = command.qualified_name.casefold()
        if key in seen:
            continue
        seen.add(key)
        rows.append(command)
    return rows


def _slash_map(bot: commands.Bot) -> dict[str, str]:
    result: dict[str, str] = {}

    def walk(node, parent=""):
        name = f"{parent} {node.name}".strip()
        result[name.casefold()] = name
        for child in getattr(node, "commands", []):
            walk(child, name)

    for node in bot.tree.get_commands(type=discord.AppCommandType.chat_input):
        walk(node)
    return result


def _usage(command: commands.Command, prefix: str) -> str:
    if command.usage:
        return f"{prefix}{command.qualified_name} {command.usage}".strip()
    signature = getattr(command, "signature", "") or ""
    return f"{prefix}{command.qualified_name} {signature}".strip()


def _description(command: commands.Command) -> str:
    raw = (command.description or command.help or "Aucune description.").strip()
    return raw.split("\n", 1)[0][:170]


def _search(commands_list: list[commands.Command], query: str) -> list[commands.Command]:
    needle = query.casefold().strip()
    if not needle:
        return []
    matches: list[tuple[int, commands.Command]] = []
    for command in commands_list:
        aliases = command.aliases or []
        name = command.qualified_name.casefold()
        alias_values = [alias.casefold() for alias in aliases]
        category = _category(command).casefold()
        description = _description(command).casefold()
        haystack = " ".join([name, *alias_values, description, category])
        if needle not in haystack:
            continue
        if needle == name or needle == command.name.casefold() or needle in alias_values:
            rank = 0
        elif name.startswith(needle):
            rank = 1
        elif any(alias.startswith(needle) for alias in alias_values):
            rank = 2
        elif needle in name:
            rank = 3
        elif needle in category:
            rank = 4
        else:
            rank = 5
        matches.append((rank, command))
    matches.sort(key=lambda item: (item[0], item[1].qualified_name.casefold()))
    return [command for _, command in matches]


def _home() -> discord.Embed:
    return embeds.standard(
        "SentriX — Centre d’aide",
        "Sélectionnez une catégorie pour consulter les commandes.",
    )


def _detail(bot: commands.Bot, command: commands.Command, prefix: str) -> discord.Embed:
    slash = _slash_map(bot).get(command.qualified_name.casefold())
    panel = embeds.standard(command.qualified_name, _description(command))
    panel.add_field(name="Utilisation", value=f"`{_usage(command, prefix)}`", inline=False)
    if slash:
        panel.add_field(name="Slash", value=f"`/{slash}`", inline=True)
    if command.aliases:
        panel.add_field(
            name="Alias",
            value=", ".join(f"`{alias}`" for alias in command.aliases[:8]),
            inline=True,
        )
    panel.add_field(name="Catégorie", value=_category(command), inline=True)
    return panel


def _pages(
    bot: commands.Bot,
    commands_list: list[commands.Command],
    prefix: str,
    title: str,
) -> list[discord.Embed]:
    slash = _slash_map(bot)
    chunks = [
        commands_list[i:i + PAGE_SIZE]
        for i in range(0, len(commands_list), PAGE_SIZE)
    ] or [[]]
    pages: list[discord.Embed] = []
    for index, chunk in enumerate(chunks, start=1):
        lines = []
        for command in chunk:
            slash_name = slash.get(command.qualified_name.casefold())
            access = f"`{prefix}{command.qualified_name}`"
            if slash_name:
                access += f"  `/{slash_name}`"
            lines.append(f"**{access}**\n{_description(command)}")
        panel = embeds.standard(
            title,
            "\n\n".join(lines) if lines else "Aucune commande dans cette catégorie.",
        )
        panel.set_footer(text=f"SentriX • Page {index}/{len(chunks)}")
        pages.append(panel)
    return pages


def _ordered_categories(bot: commands.Bot, member) -> OrderedDict[str, int]:
    grouped: OrderedDict[str, int] = OrderedDict()
    counts: dict[str, int] = {}
    for command in _visible(bot, member):
        name = _category(command)
        counts[name] = counts.get(name, 0) + 1
    for category in CATEGORY_ORDER:
        if category in counts:
            grouped[category] = counts.pop(category)
    for category in sorted(counts, key=str.casefold):
        grouped[category] = counts[category]
    return grouped


async def _private_error(interaction: discord.Interaction, text: str) -> None:
    panel = embeds.error(text)
    if interaction.response.is_done():
        await interaction.followup.send(embed=panel, ephemeral=True)
    else:
        await interaction.response.send_message(embed=panel, ephemeral=True)


class SearchModal(discord.ui.Modal, title="Rechercher une commande"):
    query = discord.ui.TextInput(
        label="Nom ou mot-clé",
        max_length=60,
        placeholder="ban, ticket, image, logs...",
    )

    def __init__(self, view: "HelpView"):
        super().__init__()
        self.help_view = view

    async def on_submit(self, interaction: discord.Interaction):
        rows = _search(
            _visible(self.help_view.bot, interaction.user),
            str(self.query.value),
        )
        pages = _pages(
            self.help_view.bot,
            rows,
            self.help_view.prefix,
            f"Recherche : {str(self.query.value)[:40]}",
        )
        view = HelpView(
            self.help_view.bot,
            self.help_view.prefix,
            interaction.user.id,
            pages=pages,
            member=interaction.user,
        )
        await interaction.response.edit_message(embed=pages[0], view=view)


class CategorySelect(discord.ui.Select):
    def __init__(self, owner: "HelpView"):
        self.owner = owner
        grouped = _ordered_categories(owner.bot, owner.member)
        options = [
            discord.SelectOption(
                label=name[:100],
                value=name,
                description=f"{count} commande(s)",
            )
            for name, count in grouped.items()
        ]
        super().__init__(
            placeholder="Sélectionnez une catégorie",
            options=options[:25],
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner.author_id:
            return await _private_error(
                interaction,
                "Ce panneau appartient à une autre personne.",
            )
        category = self.values[0]
        rows = [
            command
            for command in _visible(self.owner.bot, interaction.user)
            if _category(command) == category
        ]
        pages = _pages(self.owner.bot, rows, self.owner.prefix, category)
        # Important : on conserve le vrai discord.Member. Avant, cette information était
        # perdue après un changement de catégorie, ce qui pouvait recalculer le help comme
        # si le staff était un simple User et rendre la navigation incohérente.
        view = HelpView(
            self.owner.bot,
            self.owner.prefix,
            interaction.user.id,
            pages=pages,
            member=interaction.user,
        )
        await interaction.response.edit_message(embed=pages[0], view=view)


class HelpView(discord.ui.View):
    def __init__(
        self,
        bot: commands.Bot,
        prefix: str,
        author_id: int,
        *,
        pages: list[discord.Embed] | None = None,
        member=None,
    ):
        super().__init__(timeout=180)
        self.bot = bot
        self.prefix = prefix
        self.author_id = author_id
        self.pages = pages
        self.index = 0
        self.member = member or bot.get_user(author_id)
        self.add_item(CategorySelect(self))

        dashboard_url = os.getenv("DASHBOARD_URL", "").strip()
        if dashboard_url.startswith("https://"):
            self.add_item(
                discord.ui.Button(
                    label="Dashboard",
                    style=discord.ButtonStyle.secondary,
                    url=dashboard_url,
                    row=1,
                )
            )
        self._sync()

    def _sync(self):
        self.previous.disabled = not self.pages or self.index <= 0
        self.next.disabled = not self.pages or self.index >= len(self.pages) - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True
        await _private_error(interaction, "Ce panneau appartient à une autre personne.")
        return False

    @discord.ui.button(label="Rechercher", style=discord.ButtonStyle.secondary, row=1)
    async def search(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SearchModal(self))

    @discord.ui.button(label="Précédent", style=discord.ButtonStyle.secondary, row=2)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.pages:
            return
        self.index = max(0, self.index - 1)
        self.member = interaction.user
        self._sync()
        await interaction.response.edit_message(
            embed=self.pages[self.index],
            view=self,
        )

    @discord.ui.button(label="Accueil", style=discord.ButtonStyle.secondary, row=2)
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = HelpView(
            self.bot,
            self.prefix,
            self.author_id,
            member=interaction.user,
        )
        await interaction.response.edit_message(embed=_home(), view=view)

    @discord.ui.button(label="Suivant", style=discord.ButtonStyle.secondary, row=2)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.pages:
            return
        self.index = min(len(self.pages) - 1, self.index + 1)
        self.member = interaction.user
        self._sync()
        await interaction.response.edit_message(
            embed=self.pages[self.index],
            view=self,
        )


class OfficialHelp(commands.Cog, name="SentriXHelp"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def send_help(self, target, query: str | None = None):
        prefix = "+"
        member = getattr(target, "author", None) or getattr(target, "user", None)
        if query:
            rows = _search(_visible(self.bot, member), query)
            exact = next(
                (
                    command
                    for command in rows
                    if query.casefold()
                    in {
                        command.name.casefold(),
                        command.qualified_name.casefold(),
                        *(alias.casefold() for alias in command.aliases),
                    }
                ),
                None,
            )
            if exact:
                panel = _detail(self.bot, exact, prefix)
                if isinstance(target, commands.Context):
                    return await target.send(embed=panel)
                return await target.response.send_message(embed=panel)

            pages = _pages(
                self.bot,
                rows,
                prefix,
                f"Recherche : {query[:40]}",
            )
            view = HelpView(
                self.bot,
                prefix,
                member.id,
                pages=pages,
                member=member,
            )
            if isinstance(target, commands.Context):
                return await target.send(embed=pages[0], view=view)
            return await target.response.send_message(embed=pages[0], view=view)

        view = HelpView(self.bot, prefix, member.id, member=member)
        if isinstance(target, commands.Context):
            return await target.send(embed=_home(), view=view)
        return await target.response.send_message(embed=_home(), view=view)

    @commands.command(name="help", aliases=["aide"])
    async def prefix_help(self, ctx: commands.Context, *, query: str | None = None):
        await self.send_help(ctx, query)

    @app_commands.command(name="help", description="Ouvrir le centre d’aide SentriX")
    @app_commands.describe(commande="Nom ou mot-clé d'une commande")
    async def slash_help(
        self,
        interaction: discord.Interaction,
        commande: str | None = None,
    ):
        await self.send_help(interaction, commande)


async def setup(bot: commands.Bot):
    old = bot.get_command("help")
    if old is not None:
        bot.remove_command("help")
    bot.tree.remove_command("help", type=discord.AppCommandType.chat_input)
    await bot.add_cog(OfficialHelp(bot))
