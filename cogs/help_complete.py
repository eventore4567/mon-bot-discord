"""Aide Discord complète, catégorisée et compacte pour SentriX."""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass

import discord
from discord.ext import commands

from utils import embeds

logger = logging.getLogger("bot.help-complete")
_INSTALLED = False
_ALL_VALUE = "__sentrix_all_commands__"


@dataclass(frozen=True)
class CategorySpec:
    key: str
    emoji: str
    name: str
    summary: str
    section: str
    roots: frozenset[str] = frozenset()
    cogs: frozenset[str] = frozenset()
    prefixes: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        return f"{self.emoji} {self.name}"


CATEGORIES: tuple[CategorySpec, ...] = (
    CategorySpec(
        "ai", "🤖", "Intelligence artificielle",
        "Questions, rédaction, traduction et génération d’images.",
        "essential",
        frozenset({
            "sentrix", "summarize", "image-prompt", "image", "explain",
            "rewrite", "fact-check", "ai", "improve", "correct",
            "ai-translate", "aisetup", "aidiag",
        }),
        frozenset({"Ai"}),
    ),
    CategorySpec(
        "information", "ℹ️", "Informations",
        "Fiches du serveur, des membres, des salons et du bot.",
        "essential",
        frozenset({
            "help", "ping", "avatar", "info", "userinfo", "channelinfo",
            "membercount", "emoji-list",
        }),
        frozenset({"Utility"}),
    ),
    CategorySpec(
        "utility", "🧰", "Outils pratiques",
        "Rappels, sondages, traduction, météo et outils quotidiens.",
        "essential",
        frozenset({
            "poll", "remind", "reminder-list", "reminder-cancel",
            "translate", "weather", "suggest", "report-bug", "afk",
            "roll", "choose",
        }),
    ),
    CategorySpec(
        "economy", "💰", "Économie et boutique",
        "Argent, banque, boutique, inventaire et récompenses.",
        "community",
        frozenset({
            "balance", "economy", "daily", "weekly", "work", "rob", "pay",
            "economyleaderboard", "shop", "buy", "inventory", "sell",
            "gamble", "deposit", "withdraw", "banque", "stats",
            "shopsetup", "shoppanel", "shoprole", "give-money",
            "reset-economy",
        }),
        frozenset({"Economy", "ShopAdmin", "GamesEconomy"}),
    ),
    CategorySpec(
        "levels", "📈", "Niveaux et réputation",
        "XP, profils, classements, réputation et activité vocale.",
        "community",
        frozenset({
            "level", "leaderboard-levels", "profile", "set-bio", "rep",
            "reputation", "repleaderboard", "voice-time", "set-xp",
            "add-xp", "reset-levels", "levelcheck", "levelrepair",
            "repconfig", "repadd", "repremove", "represet", "rephistory",
        }),
        frozenset({"Levels"}),
    ),
    CategorySpec(
        "games", "🎮", "Mini-jeux",
        "Jeux rapides, quiz et parties multijoueurs.",
        "community",
        frozenset({
            "rps", "guess-number", "trivia", "tictactoe", "hangman",
            "math-quiz", "blackjack", "slots",
        }),
        frozenset({"Minigames"}),
    ),
    CategorySpec(
        "music", "🎵", "Musique",
        "Lecture, file d’attente, volume, boucle et playlists.",
        "community",
        frozenset({
            "join", "leave", "play", "pause", "resume", "skip", "stop",
            "queue", "nowplaying", "volume", "loop", "shuffle",
            "remove-from-queue", "clear-queue", "playlist-save",
            "playlist-load",
        }),
        frozenset({"Music"}),
    ),
    CategorySpec(
        "events", "🎉", "Giveaways et événements",
        "Concours, événements et tournois communautaires.",
        "community",
        frozenset({
            "giveaway-list", "giveaway-create", "giveaway-end",
            "giveaway-reroll", "giveaway-cancel", "giveaway-blacklist",
            "giveaway-unblacklist", "event-join", "event-leave",
            "event-list", "event-create", "event-cancel",
            "tournament-join", "tournament-list", "tournament-create",
            "tournament-start",
        }),
        frozenset({"Events"}),
        ("giveaway-", "event-", "tournament-"),
    ),
    CategorySpec(
        "social", "📨", "Invitations et notifications",
        "Invitations, bonus, accueil et notifications sociales.",
        "community",
        frozenset({
            "invites", "invite-leaderboard", "invited-by",
            "invitebonushistory", "addbonusinvites", "removebonusinvites",
            "notifs-ping", "notifs-list", "notifs-remove",
            "welcome-config",
        }),
        frozenset({"Invites", "Notifications"}),
        ("notifs-",),
    ),
    CategorySpec(
        "tickets", "🎫", "Tickets et support",
        "Ouverture, configuration, réouverture, transcripts et statistiques.",
        "community",
        frozenset({
            "ticket", "ticketsetup", "ticket-reopen",
            "tickettranscript", "ticketstats",
        }),
        frozenset({"Tickets"}),
        ("ticket-",),
    ),
    CategorySpec(
        "sanctions", "🔨", "Sanctions et dossiers",
        "Bans, mutes, avertissements, dossiers et quarantaine.",
        "staff",
        frozenset({
            "ban", "tempban", "unban", "kick", "mute", "unmute", "warn",
            "unwarn", "warnings", "clearwarnings", "case", "modhistory",
            "quarantine", "unquarantine", "sanctiondm",
        }),
    ),
    CategorySpec(
        "moderation", "🛡️", "Modération du serveur",
        "Messages, salons, pseudos, rôles, vocal et emojis.",
        "staff",
        frozenset({
            "clear", "say", "slowmode", "lock", "unlock", "hide", "show",
            "nickname", "resetnick", "move", "disconnect", "role-snapshot",
            "role-restore", "giverole", "removerole", "addemoji",
            "deleteemoji",
        }),
        frozenset({"Moderation"}),
    ),
    CategorySpec(
        "security", "🔒", "AutoMod et sécurité",
        "Anti-raid, anti-nuke, listes noires, sauvegardes et audits.",
        "staff",
        frozenset({
            "antiaccount", "antibot", "anticaps", "antiemoji",
            "antiinvite", "antilink", "antimention", "antinuke",
            "antiraid", "antiscam", "antispam", "automod-escalation",
            "automod-history", "automod-status", "blacklist-add",
            "blacklist-list", "blacklist-remove", "blacklist-user",
            "blacklist-users", "lockdown-server", "permission-audit",
            "security-check", "security-level", "server-backup",
            "server-restore", "syncbl", "unblacklist-user",
            "unlock-server", "unsyncbl", "unwhitelist-domain",
            "whitelist-domain",
        }),
        frozenset({"Automod", "Security"}),
        ("anti", "automod-", "blacklist-", "antinuke-"),
    ),
    CategorySpec(
        "configuration", "⚙️", "Configuration et logs",
        "Setup général, commandes, salons ignorés, logs et réglages.",
        "staff",
        frozenset({
            "setup", "logsetup", "logs-status", "config-view",
            "config-reset", "disablecommand", "enablecommand",
            "ignorechannel", "unignorechannel", "setwarnrole",
            "setwarnbanthreshold", "statsconfig",
        }),
        frozenset({"Configuration", "GamesSetup"}),
    ),
    CategorySpec(
        "server", "🏗️", "Serveur et structure",
        "Création, suppression et gestion massive de la structure.",
        "staff",
        frozenset({
            "create-server", "delete-channel", "wipe-server",
        }),
        frozenset({"ServerBuilder"}),
    ),
    CategorySpec(
        "roles", "🎭", "Rôles et vérification",
        "Panels de rôles, réactions, vérification et rôles de masse.",
        "staff",
        frozenset({
            "rolepanel", "rolepanel-refresh", "reactionrole-add",
            "reactionrole-remove", "reactionrole-list", "verify-panel",
            "set-nickname", "alias", "roleall", "massrole",
        }),
        frozenset({"Verification"}),
        ("reactionrole-",),
    ),
    CategorySpec(
        "embeds", "📣", "Embeds, annonces et design",
        "Créateur d’embeds, annonces et apparence de SentriX.",
        "staff",
        frozenset({
            "embed", "embedconfig", "announce", "designsetup",
        }),
        frozenset({"EmbedBuilder", "Design"}),
    ),
    CategorySpec(
        "stats", "📊", "Statistiques et diagnostic",
        "État du bot, croissance, statistiques et diagnostic.",
        "essential",
        frozenset({
            "bot-status", "server-growth", "command-stats", "changelog",
            "feedback", "botinfo", "diagnostic",
        }),
        frozenset({"Stats"}),
    ),
    CategorySpec(
        "owner", "🔑", "Propriétaire du bot",
        "Blacklists globales, synchronisation, statut et gestion des serveurs.",
        "staff",
        frozenset({
            "bl", "blinfo", "unbl", "editbl", "sync", "syncguild",
            "setstatus", "status-rotate", "footer", "theme", "set-bot",
            "bot-servers", "bot-leave",
        }),
        frozenset({"Owner"}),
    ),
    CategorySpec(
        "other", "🧩", "Autres commandes",
        "Commandes actives ne correspondant pas encore à une catégorie dédiée.",
        "essential",
    ),
)

CATEGORY_BY_KEY = {category.key: category for category in CATEGORIES}
SECTION_TITLES = {
    "essential": "⭐ Essentiels",
    "community": "🎉 Communauté",
    "staff": "🛡️ Administration",
}


def _command_is_hidden(command) -> bool:
    current = command
    while current is not None:
        if getattr(current, "hidden", False):
            return True
        current = getattr(current, "parent", None)
    return False


def _registered_commands(utility, bot: commands.Bot, is_staff: bool) -> list[commands.Command]:
    """Retourne uniquement les commandes réellement enregistrées dans le bot."""
    result: list[commands.Command] = []
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
        result.append(command)

    result.sort(key=lambda item: item.qualified_name.casefold())
    return result


def _category_for(command) -> CategorySpec:
    qualified_name = str(getattr(command, "qualified_name", "") or "").casefold().strip()
    root = qualified_name.split(" ", 1)[0]
    cog = getattr(command, "cog", None)
    cog_name = getattr(cog, "qualified_name", "") if cog else ""

    # Les jeux directs partagent parfois un cog économie ; leur contrat de catalogue est
    # plus précis que le nom technique du cog et doit gagner pour l'aide utilisateur.
    from .command_catalog_cleanup import GAME_COMMANDS
    if root in GAME_COMMANDS:
        return CATEGORY_BY_KEY["games"]

    # Les règles exactes passent avant les règles de cog : un même cog peut contenir
    # plusieurs catégories logiques, par exemple Utility = informations + outils.
    for category in CATEGORIES:
        if category.key == "other":
            continue
        if root in category.roots:
            return category
        if any(root.startswith(prefix) for prefix in category.prefixes):
            return category

    for category in CATEGORIES:
        if category.key != "other" and cog_name in category.cogs:
            return category

    return CATEGORY_BY_KEY["other"]


def _category_entries(utility, bot: commands.Bot, is_staff: bool):
    grouped: dict[str, list[commands.Command]] = defaultdict(list)
    for command in _registered_commands(utility, bot, is_staff):
        grouped[_category_for(command).key].append(command)

    entries = []
    for category in CATEGORIES:
        commands_list = grouped.get(category.key, [])
        if commands_list:
            entries.append((category, commands_list))
    return entries


def _commands_for_cog(utility, cog, is_staff: bool) -> list[commands.Command]:
    bot = getattr(cog, "bot", None)
    if bot is None:
        source = list(cog.walk_commands()) if hasattr(cog, "walk_commands") else list(cog.get_commands())
        return [command for command in source if not _command_is_hidden(command)]
    return [
        command
        for command in _registered_commands(utility, bot, is_staff)
        if command.cog is cog
    ]


def _command_usage(command, prefix: str) -> str:
    parts = [f"{prefix}{command.qualified_name}"]
    for name, parameter in getattr(command, "clean_params", {}).items():
        if name in {"ctx", "context", "interaction", "self"}:
            continue
        parts.append(f"<{name}>" if getattr(parameter, "required", False) else f"[{name}]")
    return " ".join(parts)


def _compact_command_line(utility, command, prefix: str, slash_names: set[str], number: int | None = None) -> str:
    usage = _command_usage(command, prefix)
    description = re.sub(r"\s+", " ", command.description or "Aucune description.").strip()
    if len(description) > 105:
        description = description[:102].rstrip() + "…"

    index = f"`{number:02d}` " if number is not None else ""
    lock = "🔒 " if utility.is_staff_command(command) else ""
    slash = "  ·  `slash`" if command.qualified_name in slash_names else ""
    return f"{index}{lock}**`{usage}`**{slash}\n└ {description}"


def _build_pages(
    utility,
    bot: commands.Bot,
    prefix: str,
    entries,
    *,
    all_mode: bool,
) -> list[discord.Embed]:
    slash_names = utility.slash_command_names(bot)
    pages: list[discord.Embed] = []
    global_index = 0

    for category, commands_list in entries:
        page_size = 12
        chunks = [
            commands_list[index:index + page_size]
            for index in range(0, len(commands_list), page_size)
        ]
        for chunk_index, chunk in enumerate(chunks, start=1):
            lines = []
            for command in chunk:
                global_index += 1
                lines.append(
                    _compact_command_line(
                        utility,
                        command,
                        prefix,
                        slash_names,
                        global_index if all_mode else None,
                    )
                )

            title = (
                f"📚 Toutes les commandes · {category.name}"
                if all_mode
                else category.label
            )
            embed = embeds.brand(
                title,
                category.summary + "\n\n" + "\n".join(lines),
            )
            embed.set_footer(
                text=(
                    f"{category.name} • page {chunk_index}/{len(chunks)} • "
                    f"{len(commands_list)} commande(s) • <obligatoire> [facultatif]"
                )
            )
            pages.append(embed)

    return pages or [embeds.brand("📖 Aide", "Aucune commande visible.")]


def _home_embed(utility, bot: commands.Bot, guild: discord.Guild | None, prefix: str, is_staff: bool) -> discord.Embed:
    entries = _category_entries(utility, bot, is_staff)
    total = sum(len(commands_list) for _, commands_list in entries)
    bot_name = bot.user.name if bot.user else "SentriX"
    server_name = guild.name if guild else "ce serveur"

    embed = embeds.brand(
        f"✦ Centre d’aide de {bot_name}",
        (
            f"Bienvenue sur le centre de commandes de **{server_name}**.\n"
            "Choisissez une catégorie dans le menu pour obtenir une liste claire, "
            "ou sélectionnez **Toutes les commandes** pour parcourir l’inventaire complet."
        ),
    )
    if bot.user:
        embed.set_thumbnail(url=bot.user.display_avatar.url)

    for section_key in ("essential", "community", "staff"):
        section_entries = [
            (category, commands_list)
            for category, commands_list in entries
            if category.section == section_key
        ]
        if not section_entries:
            continue
        lines = [
            f"{category.emoji} **{category.name}**  ·  `{len(commands_list)}`"
            for category, commands_list in section_entries
        ]
        embed.add_field(
            name=SECTION_TITLES[section_key],
            value="\n".join(lines),
            inline=section_key != "staff",
        )

    embed.add_field(
        name="⌕ Navigation rapide",
        value=(
            f"`{prefix}help ban` → détail d’une commande\n"
            "**Rechercher** → trouver par nom, alias ou description\n"
            f"**{total} commandes actives** • préfixe `{prefix}`"
        ),
        inline=False,
    )
    return embed


def install(bot: commands.Bot) -> None:
    """Installe une aide complète, logique et compacte."""
    global _INSTALLED
    if _INSTALLED:
        return

    from . import utility

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
        return _home_embed(utility, active_bot, guild, prefix, is_staff)

    def search_commands(active_bot: commands.Bot, is_staff: bool, keyword: str):
        normalized = str(keyword or "").casefold().strip()
        results = []
        for command in _registered_commands(utility, active_bot, is_staff):
            aliases = " ".join(getattr(command, "aliases", []) or [])
            haystack = f"{command.qualified_name} {aliases} {command.description or ''}".casefold()
            if normalized in haystack:
                category = _category_for(command)
                results.append((category.label, command))
        return results

    def format_command_line(command, prefix: str, slash_names: set[str]) -> str:
        return _compact_command_line(utility, command, prefix, slash_names)

    class AestheticSearchModal(discord.ui.Modal, title="⌕ Rechercher une commande"):
        mot_cle = discord.ui.TextInput(
            label="Nom, alias ou mot-clé",
            placeholder="Exemple : ticket, ban, musique…",
            max_length=60,
        )

        def __init__(self, active_bot: commands.Bot, prefix: str, is_staff: bool):
            super().__init__()
            self.bot = active_bot
            self.prefix = prefix
            self.is_staff = is_staff

        async def on_submit(self, interaction: discord.Interaction):
            results = search_commands(self.bot, self.is_staff, self.mot_cle.value)
            if not results:
                embed = embeds.brand(
                    "⌕ Aucun résultat",
                    f"Aucune commande trouvée pour **{self.mot_cle.value}**.",
                )
                return await interaction.response.edit_message(
                    embed=embed,
                    view=utility.HelpView(self.bot, self.prefix, self.is_staff),
                )

            slash_names = utility.slash_command_names(self.bot)
            chunks = [results[index:index + 10] for index in range(0, len(results), 10)]
            pages = []
            for page_index, chunk in enumerate(chunks, start=1):
                lines = []
                for label, command in chunk:
                    lines.append(
                        f"**{label}**\n"
                        + _compact_command_line(
                            utility,
                            command,
                            self.prefix,
                            slash_names,
                        )
                    )
                embed = embeds.brand(
                    f"⌕ Résultats · {self.mot_cle.value}",
                    "\n\n".join(lines),
                )
                embed.set_footer(
                    text=f"Page {page_index}/{len(chunks)} • {len(results)} résultat(s)"
                )
                pages.append(embed)

            home = _home_embed(
                utility,
                self.bot,
                interaction.guild,
                self.prefix,
                self.is_staff,
            )
            view = utility.CategoryHelpView(
                self.bot,
                self.prefix,
                self.is_staff,
                pages,
                interaction.user.id,
                home,
            )
            await interaction.response.edit_message(embed=pages[0], view=view)

    class AestheticHelpSelect(discord.ui.Select):
        def __init__(self, active_bot: commands.Bot, prefix: str, is_staff: bool):
            self.bot = active_bot
            self.prefix = prefix
            self.is_staff = is_staff
            self.entries = _category_entries(utility, active_bot, is_staff)

            total = sum(len(commands_list) for _, commands_list in self.entries)
            options = [
                discord.SelectOption(
                    label="📚 Toutes les commandes",
                    value=_ALL_VALUE,
                    description=f"{total} commandes actives",
                )
            ]
            for category, commands_list in self.entries:
                options.append(
                    discord.SelectOption(
                        label=category.label[:100],
                        value=category.key,
                        description=(
                            f"{len(commands_list)} commande(s) • {category.summary}"
                        )[:100],
                    )
                )

            super().__init__(
                placeholder="Choisissez une catégorie…",
                options=options[:25],
            )

        async def callback(self, interaction: discord.Interaction):
            selected = self.values[0]
            if selected == _ALL_VALUE:
                entries = self.entries
                pages = _build_pages(
                    utility,
                    self.bot,
                    self.prefix,
                    entries,
                    all_mode=True,
                )
            else:
                matching = next(
                    (
                        (category, commands_list)
                        for category, commands_list in self.entries
                        if category.key == selected
                    ),
                    None,
                )
                if matching is None:
                    return await interaction.response.send_message(
                        "Cette catégorie n’est plus disponible. Relancez `+help`.",
                        ephemeral=True,
                    )
                pages = _build_pages(
                    utility,
                    self.bot,
                    self.prefix,
                    [matching],
                    all_mode=False,
                )

            home = _home_embed(
                utility,
                self.bot,
                interaction.guild,
                self.prefix,
                self.is_staff,
            )
            view = utility.CategoryHelpView(
                self.bot,
                self.prefix,
                self.is_staff,
                pages,
                interaction.user.id,
                home,
            )
            await interaction.response.edit_message(embed=pages[0], view=view)

    utility.visible_commands = visible_commands
    utility.category_visible = category_visible
    utility.build_help_home = build_help_home
    utility.search_commands = search_commands
    utility.format_command_line = format_command_line
    utility.SearchModal = AestheticSearchModal
    utility.HelpSelect = AestheticHelpSelect

    _INSTALLED = True
    logger.info(
        "Aide esthétique activée : catégories logiques, pages compactes et recherche améliorée."
    )
