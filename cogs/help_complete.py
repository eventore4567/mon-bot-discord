"""Inventaire dynamique et complet des commandes affichées par +help."""

from __future__ import annotations

import logging
import re
from collections import defaultdict

import discord
from discord.ext import commands

from utils import embeds

logger = logging.getLogger("bot.help-complete")
_INSTALLED = False
_ALL_VALUE = "__sentrix_all_commands__"
_OTHER_VALUE = "__sentrix_other_categories__"


EXTRA_CATEGORY_LABELS = {
    "GamesEconomy": "🎮 Récompenses de jeux",
    "GamesSetup": "🎮 Configuration des jeux",
    "ShopAdmin": "🛒 Administration de l'économie",
    "Music": "🎵 Musique",
    "Levels": "📈 Niveaux / Communauté",
    "Invites": "📨 Invitations",
    "Stats": "📊 Statistiques / Développement",
    "Notifications": "📡 Notifications / Accueil",
    "Tickets": "🎫 Tickets",
    "Moderation": "🛡️ Modération",
    "Security": "🔐 Sécurité avancée",
    "Automod": "🔒 Sécurité / AutoMod",
    "Configuration": "⚙️ Configuration",
    "ServerBuilder": "🏗️ Création de serveur",
    "Verification": "✅ Vérification / Rôles",
    "Owner": "🔑 Propriétaire du bot",
    "EmbedBuilder": "📨 Créateur d'embeds",
    "Design": "🎨 Design et apparence",
}


def _pretty_cog_name(name: str) -> str:
    text = re.sub(r"(?<!^)(?=[A-Z])", " ", str(name or "Autres"))
    text = text.replace("_", " ").replace("-", " ")
    text = " ".join(text.split()).strip()
    return text or "Autres commandes"


def _category_label(utility, cog_name: str) -> str:
    label = utility.CATEGORY_LABELS.get(cog_name) or EXTRA_CATEGORY_LABELS.get(cog_name)
    return label or f"🧩 {_pretty_cog_name(cog_name)}"


def _command_is_hidden(command) -> bool:
    current = command
    while current is not None:
        if getattr(current, "hidden", False):
            return True
        current = getattr(current, "parent", None)
    return False


def _registered_commands(utility, bot: commands.Bot, is_staff: bool) -> list[commands.Command]:
    """Retourne seulement les commandes réellement enregistrées dans le bot."""
    commands_found: list[commands.Command] = []
    seen: set[str] = set()
    for command in bot.walk_commands():
        qualified_name = str(getattr(command, "qualified_name", "") or "").strip()
        if not qualified_name or qualified_name in seen or _command_is_hidden(command):
            continue

        cog = getattr(command, "cog", None)
        cog_name = getattr(cog, "qualified_name", "Sans catégorie") if cog else "Sans catégorie"
        if not is_staff:
            if cog_name in utility.MEMBER_HIDDEN_CATEGORIES:
                continue
            if utility.is_staff_command(command):
                continue

        seen.add(qualified_name)
        commands_found.append(command)

    commands_found.sort(key=lambda item: item.qualified_name.casefold())
    return commands_found


def _commands_for_cog(utility, cog, is_staff: bool) -> list[commands.Command]:
    bot = getattr(cog, "bot", None)
    if bot is None:
        source = list(cog.walk_commands()) if hasattr(cog, "walk_commands") else list(cog.get_commands())
        return [command for command in source if not _command_is_hidden(command)]
    return [command for command in _registered_commands(utility, bot, is_staff) if command.cog is cog]


def _category_entries(utility, bot: commands.Bot, is_staff: bool):
    grouped: dict[str, list[commands.Command]] = defaultdict(list)
    for command in _registered_commands(utility, bot, is_staff):
        cog = getattr(command, "cog", None)
        cog_name = getattr(cog, "qualified_name", "Sans catégorie") if cog else "Sans catégorie"
        grouped[cog_name].append(command)

    known_order = {name: index for index, name in enumerate(utility.CATEGORY_LABELS)}
    entries = [
        (cog_name, _category_label(utility, cog_name), commands_list)
        for cog_name, commands_list in grouped.items()
        if commands_list
    ]
    entries.sort(
        key=lambda entry: (
            0 if entry[0] in known_order else 1,
            known_order.get(entry[0], 10_000),
            utility.split_category_label(entry[1])[1].casefold(),
        )
    )
    return entries


def _chunk_lines(lines: list[str], limit: int = 900) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_length = 0
    for line in lines:
        added = len(line) + (1 if current else 0)
        if current and current_length + added > limit:
            chunks.append("\n".join(current))
            current = [line]
            current_length = len(line)
        else:
            current.append(line)
            current_length += added
    if current:
        chunks.append("\n".join(current))
    return chunks


def install(bot: commands.Bot) -> None:
    """Remplace l'inventaire fixe de +help par les commandes chargées à l'exécution."""
    global _INSTALLED
    if _INSTALLED:
        return

    from . import utility

    utility.CATEGORY_LABELS.update(EXTRA_CATEGORY_LABELS)

    def visible_commands(cog, is_staff: bool):
        return _commands_for_cog(utility, cog, is_staff)

    def category_visible(cog_name: str, cog, is_staff: bool) -> bool:
        if not is_staff and cog_name in utility.MEMBER_HIDDEN_CATEGORIES:
            return False
        return bool(_commands_for_cog(utility, cog, is_staff))

    def build_help_home(
        active_bot: commands.Bot,
        guild: discord.Guild | None,
        prefix: str,
        is_staff: bool,
    ) -> discord.Embed:
        entries = _category_entries(utility, active_bot, is_staff)
        total = sum(len(commands_list) for _, _, commands_list in entries)
        bot_name = active_bot.user.name if active_bot.user else "SentriX"
        server_name = guild.name if guild else "ce serveur"

        embed = embeds.brand(
            f"📖 Centre d'aide de {bot_name}",
            f"Toutes les commandes réellement chargées sur **{server_name}** sont inventoriées "
            f"automatiquement. Choisissez une catégorie, affichez **Toutes les commandes**, "
            f"ou utilisez **Rechercher**.\n\n"
            f"Pour le détail d'une commande : `{prefix}help nom-de-la-commande`.",
        )
        if active_bot.user:
            embed.set_thumbnail(url=active_bot.user.display_avatar.url)

        category_lines = []
        for cog_name, label, commands_list in entries:
            name = utility.split_category_label(label)[1]
            staff_suffix = " • staff" if cog_name in utility.MEMBER_HIDDEN_CATEGORIES else ""
            category_lines.append(f"• **{name}** — {len(commands_list)} commande(s){staff_suffix}")

        for index, chunk in enumerate(_chunk_lines(category_lines), start=1):
            title = "📚 Catégories disponibles" if index == 1 else "📚 Catégories — suite"
            embed.add_field(name=title, value=chunk, inline=False)

        embed.add_field(
            name="ℹ️ Inventaire automatique",
            value=(
                f"**{total} commande(s)** disponibles pour vous. Une commande ajoutée plus tard "
                "apparaîtra automatiquement ; une commande supprimée ou masquée disparaîtra de l'aide.\n"
                f"`[paramètre]` = obligatoire • `(paramètre)` = facultatif • préfixe actuel : `{prefix}`"
            ),
            inline=False,
        )
        return embed

    def search_commands(active_bot: commands.Bot, is_staff: bool, keyword: str):
        normalized = str(keyword or "").casefold().strip()
        results = []
        for command in _registered_commands(utility, active_bot, is_staff):
            cog = getattr(command, "cog", None)
            cog_name = getattr(cog, "qualified_name", "Sans catégorie") if cog else "Sans catégorie"
            aliases = " ".join(getattr(command, "aliases", []) or [])
            haystack = f"{command.qualified_name} {aliases} {command.description or ''}".casefold()
            if normalized in haystack:
                results.append((_category_label(utility, cog_name), command))
        return results

    class CompleteHelpSelect(discord.ui.Select):
        def __init__(self, active_bot: commands.Bot, prefix: str, is_staff: bool):
            self.bot = active_bot
            self.prefix = prefix
            self.is_staff = is_staff
            self.entries = _category_entries(utility, active_bot, is_staff)

            all_count = sum(len(commands_list) for _, _, commands_list in self.entries)
            options = [
                discord.SelectOption(
                    label="Toutes les commandes",
                    value=_ALL_VALUE,
                    description=f"{all_count} commande(s) chargée(s)",
                )
            ]

            direct_entries = self.entries
            overflow_entries = []
            if len(self.entries) > 24:
                direct_entries = self.entries[:23]
                overflow_entries = self.entries[23:]

            for cog_name, label, commands_list in direct_entries:
                options.append(
                    discord.SelectOption(
                        label=utility.split_category_label(label)[1][:100],
                        value=cog_name,
                        description=f"{len(commands_list)} commande(s)"[:100],
                    )
                )

            if overflow_entries:
                overflow_count = sum(len(commands_list) for _, _, commands_list in overflow_entries)
                options.append(
                    discord.SelectOption(
                        label="Autres catégories",
                        value=_OTHER_VALUE,
                        description=f"{overflow_count} commande(s) supplémentaires",
                    )
                )

            super().__init__(placeholder="Choisissez une catégorie...", options=options[:25])

        async def callback(self, interaction: discord.Interaction):
            selected = self.values[0]
            if selected == _ALL_VALUE:
                label = "📚 Toutes les commandes"
                selected_commands = _registered_commands(utility, self.bot, self.is_staff)
            elif selected == _OTHER_VALUE:
                label = "🧩 Autres catégories"
                selected_commands = [
                    command
                    for _, _, commands_list in self.entries[23:]
                    for command in commands_list
                ]
            else:
                matching = next((entry for entry in self.entries if entry[0] == selected), None)
                if matching is None:
                    return await interaction.response.send_message(
                        "Cette catégorie n'est plus disponible. Relancez +help.",
                        ephemeral=True,
                    )
                _, label, selected_commands = matching

            slash_names = utility.slash_command_names(self.bot)
            lines = [
                utility.format_command_line(command, self.prefix, slash_names)
                for command in selected_commands
            ]
            if not lines:
                embed = embeds.brand(label, "Aucune commande visible dans cette catégorie.")
                return await interaction.response.edit_message(embed=embed, view=self.view)

            chunks = [lines[index:index + 8] for index in range(0, len(lines), 8)]
            pages = []
            for page_index, chunk in enumerate(chunks, start=1):
                embed = embeds.brand(label, "\n\n".join(chunk))
                embed.set_footer(
                    text=(
                        f"Page {page_index}/{len(chunks)} • {len(lines)} commande(s) • "
                        "[paramètre] = obligatoire, (paramètre) = facultatif"
                    )
                )
                pages.append(embed)

            home_embed = build_help_home(self.bot, interaction.guild, self.prefix, self.is_staff)
            view = utility.CategoryHelpView(
                self.bot,
                self.prefix,
                self.is_staff,
                pages,
                interaction.user.id,
                home_embed,
            )
            await interaction.response.edit_message(embed=pages[0], view=view)

    utility.visible_commands = visible_commands
    utility.category_visible = category_visible
    utility.build_help_home = build_help_home
    utility.search_commands = search_commands
    utility.HelpSelect = CompleteHelpSelect

    _INSTALLED = True
    logger.info("Aide complète activée : inventaire dynamique de toutes les commandes chargées.")
