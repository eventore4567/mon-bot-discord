"""SentriX V77 — Centre d'aide Components V2, aligné sur le style du Setup.

Le moteur de commandes du help officiel reste la source de vérité. Cette couche ne masque
aucune commande : elle remplace seulement l'affichage par un panneau Components V2 avec
catégories, recherche, pagination et fiches détaillées.
"""
from __future__ import annotations

import logging
from collections import OrderedDict

import discord
from discord.ext import commands

from utils import embeds
from utils import sentrix_panels as panels
from utils.command_permissions import command_example, command_requirement
from . import help as legacy
from . import setup_components_v73 as setup_v73

logger = logging.getLogger("bot.help-components-v77")

RUNTIME_MARKER = "Help Components V2 V77"
PAGE_SIZE = 6

CATEGORY_META = OrderedDict(
    (
        ("moderation", ("🛡️", "Modération", "Ban, kick, mute, warn, clear et gestion des sanctions.")),
        ("security", ("🔒", "Sécurité", "Anti-spam, anti-raid, vérification et protections du serveur.")),
        ("tickets", ("🎫", "Tickets", "Support, panels, tickets et outils liés aux demandes.")),
        ("community", ("👋", "Bienvenue & rôles", "Bienvenue, rôles, autorôles et outils de communauté.")),
        ("logs", ("📜", "Logs", "Journaux du serveur, historique et suivi des actions.")),
        ("economy", ("🪙", "Économie & niveaux", "Argent, banque, boutique, XP, niveaux et progression.")),
        ("ai", ("🧠", "Intelligence artificielle", "Assistant SentriX, recherche, mémoire et génération d'images.")),
        ("notifications", ("🔔", "Notifications", "YouTube, TikTok, Twitch et rôles de notification.")),
        ("games", ("🎮", "Jeux & événements", "Mini-jeux, giveaways, activités et divertissement.")),
        ("music", ("🎵", "Musique", "Lecture et commandes musicales disponibles sur SentriX.")),
        ("utility", ("🛠️", "Utilitaires", "Informations, statistiques, serveur, membre et outils pratiques.")),
        ("administration", ("⚙️", "Administration", "Configuration et outils avancés pour gérer le serveur.")),
    )
)

COG_CATEGORY = {
    "Moderation": "moderation",
    "Automod": "security",
    "Security": "security",
    "SecurityTools": "security",
    "Verification": "security",
    "ProofVerification": "security",
    "Tickets": "tickets",
    "Welcome": "community",
    "Roles": "community",
    "RolePanel": "community",
    "ReactionRoles": "community",
    "Logs": "logs",
    "Economy": "economy",
    "Levels": "economy",
    "GamesEconomy": "games",
    "Minigames": "games",
    "Events": "games",
    "Music": "music",
    "Ai": "ai",
    "AI": "ai",
    "Notifications": "notifications",
    "Utility": "utility",
    "Stats": "utility",
    "Invites": "utility",
    "Configuration": "administration",
    "ServerBuilder": "administration",
    "Owner": "administration",
    "EmbedBuilder": "administration",
    "Design": "administration",
}

LEGACY_CATEGORY_FALLBACK = {
    "Modération": "moderation",
    "Tickets": "tickets",
    "IA": "ai",
    "Économie": "economy",
    "Jeux": "games",
    "Informations": "utility",
    "Administration": "administration",
}


def _cog_name(command: commands.Command) -> str:
    return getattr(command.cog, "qualified_name", "Utility") if command.cog else "Utility"


def _category_key(command: commands.Command) -> str:
    cog = _cog_name(command)
    if cog in COG_CATEGORY:
        return COG_CATEGORY[cog]

    folded = cog.casefold()
    if "moder" in folded:
        return "moderation"
    if any(word in folded for word in ("security", "secur", "automod", "verification")):
        return "security"
    if "ticket" in folded:
        return "tickets"
    if any(word in folded for word in ("welcome", "role", "community")):
        return "community"
    if "log" in folded:
        return "logs"
    if any(word in folded for word in ("econom", "level", "shop")):
        return "economy"
    if folded in {"ai", "ia"} or "artificial" in folded:
        return "ai"
    if "notif" in folded:
        return "notifications"
    if any(word in folded for word in ("game", "event", "giveaway", "minigame")):
        return "games"
    if "music" in folded:
        return "music"
    return LEGACY_CATEGORY_FALLBACK.get(legacy._category(command), "administration")


def _all_rows(bot: commands.Bot, member=None) -> list[commands.Command]:
    return legacy._visible(bot, member)


def _grouped(bot: commands.Bot, member=None) -> OrderedDict[str, list[commands.Command]]:
    buckets: dict[str, list[commands.Command]] = {}
    for command in _all_rows(bot, member):
        buckets.setdefault(_category_key(command), []).append(command)

    result: OrderedDict[str, list[commands.Command]] = OrderedDict()
    for key in CATEGORY_META:
        rows = buckets.pop(key, [])
        if rows:
            rows.sort(key=lambda command: command.qualified_name.casefold())
            result[key] = rows
    for key in sorted(buckets):
        rows = buckets[key]
        rows.sort(key=lambda command: command.qualified_name.casefold())
        result[key] = rows
    return result


def _meta(key: str) -> tuple[str, str, str]:
    return CATEGORY_META.get(key, ("📦", key.replace("_", " ").title(), "Commandes SentriX."))


def _slash_name(bot: commands.Bot, command: commands.Command) -> str | None:
    return legacy._slash_map(bot).get(command.qualified_name.casefold())


def _command_title(bot: commands.Bot, command: commands.Command, prefix: str) -> str:
    slash = _slash_name(bot, command)
    parts: list[str] = []
    if slash:
        parts.append(f"/{slash}")
    parts.append(f"{prefix}{command.qualified_name}")
    return " · ".join(parts)


def _command_summary(bot: commands.Bot, command: commands.Command, prefix: str) -> str:
    return (
        f"### {_command_title(bot, command, prefix)}\n"
        f"{legacy._description(command)}\n"
        f"**Permission :** {command_requirement(command)}"
    )


def _chunks(rows: list[commands.Command]) -> list[list[commands.Command]]:
    return [rows[index:index + PAGE_SIZE] for index in range(0, len(rows), PAGE_SIZE)] or [[]]


def _search_rows(bot: commands.Bot, member, query: str) -> list[commands.Command]:
    return legacy._search(_all_rows(bot, member), query)


def _exact(rows: list[commands.Command], query: str) -> commands.Command | None:
    return legacy._exact_match(rows, query)


def _link_buttons(bot: commands.Bot) -> list[discord.ui.Button]:
    buttons: list[discord.ui.Button] = []
    for label, url in (
        ("Ajouter SentriX", legacy._invite_url(bot)),
        ("Dashboard", legacy._dashboard_url()),
        ("Serveur support", legacy._support_url()),
    ):
        if url:
            buttons.append(discord.ui.Button(label=label, style=discord.ButtonStyle.link, url=url))
    return buttons[:5]


async def _private_error(interaction: discord.Interaction, text: str) -> None:
    panel = embeds.error(text)
    if interaction.response.is_done():
        await panels.envoyer(interaction.followup, panels.depuis_embed(panel), ephemere=True)
    else:
        await panels.envoyer(interaction.response, panels.depuis_embed(panel), ephemere=True)


class HelpSearchModalV77(discord.ui.Modal, title="Rechercher une commande"):
    query = discord.ui.TextInput(
        label="Nom ou mot-clé",
        placeholder="ban, ticket, image, logs...",
        min_length=1,
        max_length=60,
    )

    def __init__(self, view: "SentriXHelpV77"):
        super().__init__(timeout=300)
        self.help_view = view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        query = str(self.query.value).strip()
        rows = _search_rows(self.help_view.bot, interaction.user, query)
        exact = _exact(rows, query)
        if exact is not None:
            self.help_view.show_detail(exact)
        else:
            self.help_view.show_search(query, rows)
        if not interaction.response.is_done():
            await interaction.response.defer()
        await self.help_view._edit(interaction)


class SentriXHelpV77(discord.ui.LayoutView):
    """Interface d'aide Components V2, visuellement alignée avec +setup."""

    def __init__(self, bot: commands.Bot, prefix: str, author_id: int, *, member=None):
        super().__init__(timeout=900)
        self.bot = bot
        self.prefix = prefix
        self.author_id = int(author_id)
        self.member = member or bot.get_user(author_id)

        self.mode = "home"
        self.category_key: str | None = None
        self.rows: list[commands.Command] = []
        self.index = 0
        self.query: str | None = None
        self.command: commands.Command | None = None
        self.return_mode = "home"
        self.return_category: str | None = None
        self.return_rows: list[commands.Command] = []
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
        self.command = None

    def show_category(self, key: str) -> None:
        self.mode = "category"
        self.category_key = key
        self.rows = list(_grouped(self.bot, self.member).get(key, []))
        self.index = 0
        self.query = None
        self.command = None

    def show_search(self, query: str, rows: list[commands.Command] | None = None) -> None:
        self.mode = "search"
        self.category_key = None
        self.query = query.strip()
        self.rows = list(rows if rows is not None else _search_rows(self.bot, self.member, query))
        self.index = 0
        self.command = None

    def show_detail(self, command: commands.Command) -> None:
        self.return_mode = self.mode
        self.return_category = self.category_key
        self.return_rows = list(self.rows)
        self.return_index = self.index
        self.return_query = self.query
        self.mode = "detail"
        self.command = command

    def go_back_from_detail(self) -> None:
        if self.return_mode == "category":
            self.mode = "category"
            self.category_key = self.return_category
            self.rows = list(self.return_rows)
            self.index = self.return_index
            self.query = None
        elif self.return_mode == "search":
            self.mode = "search"
            self.category_key = None
            self.rows = list(self.return_rows)
            self.index = self.return_index
            self.query = self.return_query
        else:
            self.show_home()
        self.command = None

    async def refresh(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            await interaction.response.defer()
        await self._edit(interaction)

    async def _edit(self, interaction: discord.Interaction) -> None:
        self.rebuild()
        await interaction.edit_original_response(content=None, embed=None, attachments=[], view=self)

    def rebuild(self) -> None:
        self.clear_items()
        if self.mode == "category":
            self._build_list(category=self.category_key)
        elif self.mode == "search":
            self._build_list(category=None)
        elif self.mode == "detail":
            self._build_detail()
        elif self.mode == "closed":
            self._build_closed()
        else:
            self._build_home()

    def _build_home(self) -> None:
        grouped = _grouped(self.bot, self.member)
        total = sum(len(rows) for rows in grouped.values())
        slash_count = len(legacy._slash_map(self.bot))

        container = discord.ui.Container(accent_colour=setup_v73.ACCENT)
        container.add_item(
            discord.ui.Section(
                discord.ui.TextDisplay(
                    "# Centre d'aide SentriX\n"
                    "**Bienvenue dans l'aide de SentriX.** Choisissez une catégorie pour voir "
                    "les commandes, ou utilisez la recherche pour trouver directement ce qu'il vous faut.\n\n"
                    f"**{total} commandes disponibles** · **{slash_count} commandes slash détectées**\n"
                    "Toutes les commandes restent visibles, y compris les commandes administratives ; "
                    "la permission nécessaire est affichée sur chaque fiche."
                ),
                accessory=setup_v73._thumbnail(self.bot),
            )
        )
        container.add_item(discord.ui.Separator())

        visible_keys = list(grouped.keys())
        for index, key in enumerate(visible_keys):
            emoji, label, description = _meta(key)
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
            if index in {1, 4, 7} and index < len(visible_keys) - 1:
                container.add_item(discord.ui.Separator())

        search = discord.ui.Button(label="Rechercher une commande", style=discord.ButtonStyle.primary, emoji="🔎")
        close = discord.ui.Button(label="Fermer", style=discord.ButtonStyle.danger)

        async def open_search(interaction: discord.Interaction):
            await interaction.response.send_modal(HelpSearchModalV77(self))

        async def close_help(interaction: discord.Interaction):
            self.mode = "closed"
            await self.refresh(interaction)
            self.stop()

        search.callback = open_search
        close.callback = close_help
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.ActionRow(search, close))

        links = _link_buttons(self.bot)
        if links:
            container.add_item(discord.ui.ActionRow(*links))
        self.add_item(container)

    def _build_list(self, category: str | None) -> None:
        if self.mode == "category" and category is not None:
            emoji, label, description = _meta(category)
            title = f"{emoji} {label}"
            subtitle = description
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
                    f"# {title}\n{subtitle}\n"
                    f"**{len(self.rows)} commande(s)** · page **{self.index + 1}/{len(pages)}**"
                ),
                accessory=setup_v73._thumbnail(self.bot),
            )
        )
        container.add_item(discord.ui.Separator())

        if not chunk:
            container.add_item(
                discord.ui.TextDisplay(
                    "### Aucun résultat\nAucune commande ne correspond à cette recherche. Essayez un autre mot-clé."
                )
            )
        else:
            for command in chunk:
                detail = discord.ui.Button(label="Détails", style=discord.ButtonStyle.secondary)

                async def open_detail(interaction: discord.Interaction, selected=command):
                    self.show_detail(selected)
                    await self.refresh(interaction)

                detail.callback = open_detail
                container.add_item(
                    discord.ui.Section(
                        discord.ui.TextDisplay(_command_summary(self.bot, command, self.prefix)),
                        accessory=detail,
                    )
                )

        back = discord.ui.Button(label="Accueil", style=discord.ButtonStyle.primary, emoji="↩️")
        previous = discord.ui.Button(label="Précédent", style=discord.ButtonStyle.secondary, disabled=self.index <= 0)
        next_button = discord.ui.Button(
            label="Suivant",
            style=discord.ButtonStyle.secondary,
            disabled=self.index >= len(pages) - 1,
        )
        search = discord.ui.Button(label="Rechercher", style=discord.ButtonStyle.secondary, emoji="🔎")
        close = discord.ui.Button(label="Fermer", style=discord.ButtonStyle.danger)

        async def go_home(interaction: discord.Interaction):
            self.show_home()
            await self.refresh(interaction)

        async def go_previous(interaction: discord.Interaction):
            if self.index > 0:
                self.index -= 1
            await self.refresh(interaction)

        async def go_next(interaction: discord.Interaction):
            if self.index < len(pages) - 1:
                self.index += 1
            await self.refresh(interaction)

        async def open_search(interaction: discord.Interaction):
            await interaction.response.send_modal(HelpSearchModalV77(self))

        async def close_help(interaction: discord.Interaction):
            self.mode = "closed"
            await self.refresh(interaction)
            self.stop()

        back.callback = go_home
        previous.callback = go_previous
        next_button.callback = go_next
        search.callback = open_search
        close.callback = close_help
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.ActionRow(back, previous, next_button, search, close))
        self.add_item(container)

    def _build_detail(self) -> None:
        command = self.command
        if command is None:
            self.show_home()
            return self._build_home()

        slash = _slash_name(self.bot, command)
        emoji, category_label, _description = _meta(_category_key(command))
        usage = legacy._usage(command, self.prefix)
        example = command_example(command, self.prefix)
        aliases = ", ".join(f"`{alias}`" for alias in command.aliases[:12]) if command.aliases else "Aucun"

        command_lines = [f"`{usage}`"]
        if slash:
            command_lines.insert(0, f"`/{slash}`")

        container = discord.ui.Container(accent_colour=setup_v73.ACCENT)
        container.add_item(
            discord.ui.Section(
                discord.ui.TextDisplay(
                    f"# {_command_title(self.bot, command, self.prefix)}\n{legacy._description(command)}"
                ),
                accessory=setup_v73._thumbnail(self.bot),
            )
        )
        container.add_item(discord.ui.Separator())
        container.add_item(
            discord.ui.TextDisplay(
                "### Utilisation\n"
                + "\n".join(command_lines)
                + "\n\n### Permission nécessaire\n"
                + command_requirement(command)
                + f"\n\n### Catégorie\n{emoji} {category_label}"
                + f"\n\n### Exemple\n`{example}`"
                + f"\n\n### Alias\n{aliases}"
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
            await interaction.response.send_modal(HelpSearchModalV77(self))

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

    def _build_closed(self) -> None:
        self.add_item(
            discord.ui.Container(
                discord.ui.TextDisplay(
                    "# Aide fermée\nLe centre d'aide SentriX a été fermé. Relancez `+help` ou `/help` pour le rouvrir."
                ),
                accent_colour=setup_v73.ACCENT,
            )
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception, item=None) -> None:
        logger.error("Erreur Help Components V77", exc_info=(type(error), error, error.__traceback__))
        try:
            await _private_error(interaction, "Une erreur est survenue dans le centre d'aide SentriX.")
        except discord.HTTPException:
            pass


async def _send_help_v77(self, target, query: str | None = None):
    prefix = "+"
    member = getattr(target, "author", None) or getattr(target, "user", None)
    if member is None:
        return

    view = SentriXHelpV77(self.bot, prefix, member.id, member=member)
    if query:
        rows = _search_rows(self.bot, member, query)
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
    if getattr(bot, "_sentrix_help_components_v77", False):
        return
    if not hasattr(discord.ui, "LayoutView"):
        raise RuntimeError("SentriX Help V77 exige discord.py 2.6+ (Components V2).")

    current = legacy.OfficialHelp.send_help
    if not getattr(current, "_sentrix_help_components_v77", False):
        _send_help_v77._sentrix_help_components_v77 = True
        _send_help_v77._sentrix_previous = current
        legacy.OfficialHelp.send_help = _send_help_v77

    bot._sentrix_help_components_v77 = True
    logger.info(
        "%s installé : +help et /help utilisent désormais le même langage visuel que +setup.",
        RUNTIME_MARKER,
    )


__all__ = ["SentriXHelpV77", "install"]
