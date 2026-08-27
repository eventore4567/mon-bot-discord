"""Centre d'aide officiel SentriX.

+help et /help partagent la même logique. L'accueil reste volontairement léger :
il sert à trouver une commande, pas à configurer le serveur.
"""
from __future__ import annotations

import os
from collections import OrderedDict
from urllib.parse import urlparse

import discord
from discord import app_commands
from discord.ext import commands

import config
from utils import embeds
from utils.command_permissions import command_example, command_requirement

PAGE_SIZE = 7

CATEGORY_NAMES = {
    "Moderation": "Modération",
    "Automod": "Administration",
    "Security": "Administration",
    "SecurityTools": "Administration",
    "Configuration": "Administration",
    "Logs": "Administration",
    "ServerBuilder": "Administration",
    "Verification": "Administration",
    "Owner": "Administration",
    "EmbedBuilder": "Administration",
    "Design": "Administration",
    "Utility": "Informations",
    "Stats": "Informations",
    "Invites": "Informations",
    "Economy": "Économie",
    "Levels": "Économie",
    "GamesEconomy": "Jeux",
    "Minigames": "Jeux",
    "Music": "Jeux",
    "Events": "Jeux",
    "Tickets": "Tickets",
    "Ai": "IA",
    "Notifications": "Administration",
}

CATEGORY_ORDER = (
    "Modération",
    "Informations",
    "Économie",
    "Jeux",
    "Tickets",
    "IA",
    "Administration",
)

CATEGORY_DESCRIPTIONS = {
    "Modération": "Ban, kick, mute, warn, clear et sanctions.",
    "Informations": "Serveur, membre, rôle, statistiques et utilitaires.",
    "Économie": "Balance, banque, boutique, niveaux et progression.",
    "Jeux": "Mini-jeux, activités et commandes de divertissement.",
    "Tickets": "Commandes liées aux tickets et au support.",
    "IA": "Assistant SentriX et génération d’images.",
    "Administration": "Configuration, sécurité, logs, rôles et gestion du serveur.",
}

INVITE_PERMISSION_NAMES = (
    "view_channel", "manage_channels", "manage_roles", "kick_members", "ban_members",
    "moderate_members", "manage_messages", "read_message_history", "send_messages",
    "send_messages_in_threads", "embed_links", "attach_files", "add_reactions",
    "mention_everyone", "manage_nicknames", "change_nickname", "manage_webhooks",
    "manage_emojis_and_stickers", "connect", "speak", "move_members", "mute_members",
    "deafen_members", "use_application_commands", "create_public_threads",
    "create_private_threads", "manage_threads", "manage_events",
)


def _cog_name(command: commands.Command) -> str:
    return getattr(command.cog, "qualified_name", "Utility") if command.cog else "Utility"


def _category(command: commands.Command) -> str:
    return CATEGORY_NAMES.get(_cog_name(command), "Informations")


def _visible(bot: commands.Bot, _member=None) -> list[commands.Command]:
    """Toutes les commandes réelles sont visibles dans l'aide, permission ou non."""
    rows: list[commands.Command] = []
    seen: set[str] = set()
    for command in bot.walk_commands():
        if command.hidden:
            continue
        key = command.qualified_name.casefold()
        if key in seen:
            continue
        seen.add(key)
        rows.append(command)
    return rows


def _slash_map(bot: commands.Bot) -> dict[str, str]:
    result: dict[str, str] = {}

    def walk(node, parent: str = "") -> None:
        name = f"{parent} {node.name}".strip()
        result[name.casefold()] = name
        for child in getattr(node, "commands", []):
            walk(child, name)

    for node in bot.tree.get_commands(type=discord.AppCommandType.chat_input):
        walk(node)
    return result


def _description(command: commands.Command) -> str:
    raw = (command.description or command.help or "Aucune description.").strip()
    return raw.split("\n", 1)[0][:220]


def _usage(command: commands.Command, prefix: str) -> str:
    if command.usage:
        return f"{prefix}{command.qualified_name} {command.usage}".strip()
    signature = getattr(command, "signature", "") or ""
    return f"{prefix}{command.qualified_name} {signature}".strip()


def _command_label(bot: commands.Bot, command: commands.Command, prefix: str) -> str:
    slash = _slash_map(bot).get(command.qualified_name.casefold())
    label = f"{prefix}{command.qualified_name}"
    if slash:
        label += f"   /{slash}"
    return label[:256]


def _decorate(panel: discord.Embed, bot: commands.Bot) -> discord.Embed:
    user = getattr(bot, "user", None)
    avatar = getattr(getattr(user, "display_avatar", None), "url", None)
    if avatar:
        panel.set_thumbnail(url=str(avatar))
    return panel


def _home(bot: commands.Bot, member=None) -> discord.Embed:
    grouped = _ordered_categories(bot, member)
    panel = embeds.help_embed(
        "SentriX — Centre d’aide",
        "Retrouvez rapidement les commandes et fonctionnalités de SentriX.",
    )
    lines = []
    for category, count in grouped.items():
        description = CATEGORY_DESCRIPTIONS.get(category, "Commandes SentriX.")
        lines.append(f"**{category}** — {description} `{count}`")
    panel.add_field(name="Catégories", value="\n".join(lines), inline=False)
    panel.add_field(
        name="Recherche rapide",
        value="Tapez `+help ban`, `/help commande:ban` ou utilisez **Rechercher**.",
        inline=False,
    )
    panel.add_field(
        name="Permissions",
        value="Toutes les commandes sont visibles. La fiche d’une commande indique clairement la permission nécessaire.",
        inline=False,
    )
    panel.set_footer(text="SentriX • Centre d’aide")
    return _decorate(panel, bot)


def _detail(bot: commands.Bot, command: commands.Command, prefix: str) -> discord.Embed:
    slash = _slash_map(bot).get(command.qualified_name.casefold())
    requirement = command_requirement(command)
    panel = embeds.help_embed(f"SentriX — {command.qualified_name}", _description(command))
    panel.add_field(name="Commande", value=f"`{_usage(command, prefix)}`", inline=False)
    if slash:
        panel.add_field(name="Slash", value=f"`/{slash}`", inline=True)
    panel.add_field(name="Permission nécessaire", value=requirement, inline=True)
    panel.add_field(name="Catégorie", value=_category(command), inline=True)
    panel.add_field(name="Exemple", value=f"`{command_example(command, prefix)}`", inline=False)
    if command.aliases:
        panel.add_field(
            name="Alias",
            value=", ".join(f"`{alias}`" for alias in command.aliases[:10]),
            inline=False,
        )
    panel.set_footer(text="SentriX • Aide commande")
    return _decorate(panel, bot)


def _pages(bot: commands.Bot, command_rows: list[commands.Command], prefix: str, title: str) -> list[discord.Embed]:
    chunks = [command_rows[i:i + PAGE_SIZE] for i in range(0, len(command_rows), PAGE_SIZE)] or [[]]
    pages: list[discord.Embed] = []
    for page_index, chunk in enumerate(chunks, start=1):
        panel = embeds.help_embed(
            f"SentriX — {title}",
            "Sélectionnez ou recherchez une commande pour afficher sa fiche complète.",
        )
        if not chunk:
            panel.add_field(name="Aucun résultat", value="Aucune commande trouvée.", inline=False)
        else:
            for command in chunk:
                panel.add_field(
                    name=_command_label(bot, command, prefix),
                    value=f"{_description(command)}\n**Permission :** {command_requirement(command)}",
                    inline=False,
                )
        panel.set_footer(text=f"SentriX • Page {page_index}/{len(chunks)}")
        pages.append(_decorate(panel, bot))
    return pages


def _ordered_categories(bot: commands.Bot, member=None) -> OrderedDict[str, int]:
    counts: dict[str, int] = {}
    for command in _visible(bot, member):
        category = _category(command)
        counts[category] = counts.get(category, 0) + 1

    result: OrderedDict[str, int] = OrderedDict()
    for category in CATEGORY_ORDER:
        if category in counts:
            result[category] = counts.pop(category)
    for category in sorted(counts, key=str.casefold):
        result[category] = counts[category]
    return result


def _search(command_rows: list[commands.Command], query: str) -> list[commands.Command]:
    needle = query.casefold().strip().lstrip("+/")
    if not needle:
        return []
    ranked: list[tuple[int, commands.Command]] = []
    for command in command_rows:
        aliases = [alias.casefold() for alias in (command.aliases or [])]
        name = command.qualified_name.casefold()
        category = _category(command).casefold()
        description = _description(command).casefold()
        haystack = " ".join([name, *aliases, category, description])
        if needle not in haystack:
            continue
        if needle == name or needle == command.name.casefold() or needle in aliases:
            rank = 0
        elif name.startswith(needle):
            rank = 1
        elif needle in name:
            rank = 2
        elif needle in category:
            rank = 3
        else:
            rank = 4
        ranked.append((rank, command))
    ranked.sort(key=lambda row: (row[0], row[1].qualified_name.casefold()))
    return [command for _, command in ranked]


def _recommended_invite_permissions() -> discord.Permissions:
    permissions = discord.Permissions.none()
    for name in INVITE_PERMISSION_NAMES:
        if hasattr(permissions, name):
            setattr(permissions, name, True)
    return permissions


def _invite_url(bot: commands.Bot) -> str | None:
    client_id = getattr(getattr(bot, "user", None), "id", None)
    if client_id is None:
        configured = str(getattr(config, "DISCORD_CLIENT_ID", "") or "").strip()
        if configured.isdigit():
            client_id = int(configured)
    if client_id is None:
        return None
    return discord.utils.oauth_url(
        int(client_id), permissions=_recommended_invite_permissions(), scopes=("bot", "applications.commands")
    )


def _valid_http_url(value: str) -> str | None:
    value = str(value or "").strip()
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        return None
    return value


def _dashboard_url() -> str | None:
    legacy = os.getenv("DASHBOARD_URL", "").strip()
    return _valid_http_url(legacy) or _valid_http_url(getattr(config, "DASHBOARD_APP_URL", ""))


def _support_url() -> str | None:
    for env_name in ("SENTRIX_SUPPORT_URL", "SUPPORT_SERVER_URL"):
        value = _valid_http_url(os.getenv(env_name, ""))
        if value:
            return value
    return None


def _add_growth_links(view: discord.ui.View, bot: commands.Bot) -> None:
    for label, url in (
        ("Ajouter SentriX", _invite_url(bot)),
        ("Dashboard", _dashboard_url()),
        ("Serveur support", _support_url()),
    ):
        if url:
            view.add_item(discord.ui.Button(label=label, style=discord.ButtonStyle.link, url=url, row=3))


async def _private_error(interaction: discord.Interaction, text: str) -> None:
    panel = embeds.error(text)
    if interaction.response.is_done():
        await interaction.followup.send(embed=panel, ephemeral=True)
    else:
        await interaction.response.send_message(embed=panel, ephemeral=True)


def _exact_match(rows: list[commands.Command], query: str) -> commands.Command | None:
    needle = query.casefold().strip().lstrip("+/")
    return next(
        (
            command for command in rows
            if needle in {
                command.name.casefold(), command.qualified_name.casefold(),
                *(alias.casefold() for alias in command.aliases),
            }
        ),
        None,
    )


class SearchModal(discord.ui.Modal, title="Rechercher une commande"):
    query = discord.ui.TextInput(label="Nom ou mot-clé", max_length=60, placeholder="ban, ticket, image, logs...")

    def __init__(self, view: "HelpView"):
        super().__init__()
        self.help_view = view

    async def on_submit(self, interaction: discord.Interaction):
        rows = _search(_visible(self.help_view.bot, interaction.user), str(self.query.value))
        exact = _exact_match(rows, str(self.query.value))
        if exact:
            view = HelpView(self.help_view.bot, self.help_view.prefix, interaction.user.id, member=interaction.user)
            return await interaction.response.edit_message(
                content=None, embed=_detail(self.help_view.bot, exact, self.help_view.prefix), view=view,
            )
        pages = _pages(self.help_view.bot, rows, self.help_view.prefix, f"Recherche : {str(self.query.value)[:40]}")
        view = HelpView(self.help_view.bot, self.help_view.prefix, interaction.user.id, pages=pages, member=interaction.user)
        await interaction.response.edit_message(content=None, embed=pages[0], view=view)


class CategorySelect(discord.ui.Select):
    def __init__(self, owner: "HelpView"):
        self.owner = owner
        options = [
            discord.SelectOption(
                label=name[:100], value=name,
                description=CATEGORY_DESCRIPTIONS.get(name, f"{count} commande(s)")[:100],
            )
            for name, count in _ordered_categories(owner.bot, owner.member).items()
        ]
        if not options:
            options = [discord.SelectOption(label="Aucune catégorie", value="__empty__")]
        super().__init__(placeholder="Choisir une catégorie", options=options[:25], row=0)

    async def callback(self, interaction: discord.Interaction):
        category = self.values[0]
        if category == "__empty__":
            return await _private_error(interaction, "Aucune catégorie disponible.")
        rows = [command for command in _visible(self.owner.bot, interaction.user) if _category(command) == category]
        pages = _pages(self.owner.bot, rows, self.owner.prefix, category)
        view = HelpView(self.owner.bot, self.owner.prefix, interaction.user.id, pages=pages, member=interaction.user)
        await interaction.response.edit_message(content=None, embed=pages[0], view=view)


class HelpView(discord.ui.View):
    def __init__(self, bot: commands.Bot, prefix: str, author_id: int, *, pages=None, member=None):
        super().__init__(timeout=180)
        self.bot = bot
        self.prefix = prefix
        self.author_id = int(author_id)
        self.pages = pages
        self.index = 0
        self.member = member or bot.get_user(author_id)
        self.add_item(CategorySelect(self))
        _add_growth_links(self, bot)
        self._sync()

    def _sync(self) -> None:
        self.previous.disabled = not self.pages or self.index <= 0
        self.next.disabled = not self.pages or self.index >= len(self.pages) - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True
        await _private_error(interaction, "Ce panneau d’aide appartient à une autre personne.")
        return False

    @discord.ui.button(label="Rechercher", style=discord.ButtonStyle.secondary, row=1)
    async def search(self, interaction: discord.Interaction, _button: discord.ui.Button):
        await interaction.response.send_modal(SearchModal(self))

    @discord.ui.button(label="Précédent", style=discord.ButtonStyle.secondary, row=2)
    async def previous(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if not self.pages:
            return
        self.index = max(0, self.index - 1)
        self._sync()
        await interaction.response.edit_message(content=None, embed=self.pages[self.index], view=self)

    @discord.ui.button(label="Accueil", style=discord.ButtonStyle.secondary, row=2)
    async def home(self, interaction: discord.Interaction, _button: discord.ui.Button):
        view = HelpView(self.bot, self.prefix, self.author_id, member=interaction.user)
        await interaction.response.edit_message(content=None, embed=_home(self.bot, interaction.user), view=view)

    @discord.ui.button(label="Suivant", style=discord.ButtonStyle.secondary, row=2)
    async def next(self, interaction: discord.Interaction, _button: discord.ui.Button):
        if not self.pages:
            return
        self.index = min(len(self.pages) - 1, self.index + 1)
        self._sync()
        await interaction.response.edit_message(content=None, embed=self.pages[self.index], view=self)


class OfficialHelp(commands.Cog, name="SentriXHelp"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def send_help(self, target, query: str | None = None):
        prefix = "+"
        member = getattr(target, "author", None) or getattr(target, "user", None)
        if member is None:
            return

        if query:
            rows = _search(_visible(self.bot, member), query)
            exact = _exact_match(rows, query)
            if exact:
                panel = _detail(self.bot, exact, prefix)
                if isinstance(target, commands.Context):
                    return await target.send(content=None, embed=panel)
                return await target.response.send_message(content=None, embed=panel)

            pages = _pages(self.bot, rows, prefix, f"Recherche : {query[:40]}")
            view = HelpView(self.bot, prefix, member.id, pages=pages, member=member)
            if isinstance(target, commands.Context):
                return await target.send(content=None, embed=pages[0], view=view)
            return await target.response.send_message(content=None, embed=pages[0], view=view)

        panel = _home(self.bot, member)
        view = HelpView(self.bot, prefix, member.id, member=member)
        if isinstance(target, commands.Context):
            return await target.send(content=None, embed=panel, view=view)
        return await target.response.send_message(content=None, embed=panel, view=view)

    @commands.command(name="help", aliases=["aide"])
    async def prefix_help(self, ctx: commands.Context, *, query: str | None = None):
        await self.send_help(ctx, query)

    @app_commands.command(name="help", description="Ouvrir le centre d’aide SentriX")
    @app_commands.describe(commande="Nom ou mot-clé d'une commande")
    async def slash_help(self, interaction: discord.Interaction, commande: str | None = None):
        await self.send_help(interaction, commande)


async def setup(bot: commands.Bot):
    old = bot.get_command("help")
    if old is not None:
        bot.remove_command("help")
    bot.tree.remove_command("help", type=discord.AppCommandType.chat_input)
    await bot.add_cog(OfficialHelp(bot))
