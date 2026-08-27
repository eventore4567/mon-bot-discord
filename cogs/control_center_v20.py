"""SentriX V20 — points d’entrée unifiés +setup, /setup, +help et /help."""
from __future__ import annotations

import time

import discord
from discord import app_commands
from discord.ext import commands

import main as bot_main
from utils import checks, embeds
from utils.control_center_v20_access import (
    _can_open_setup, _install_global_manager_table, _install_strict_permission_policy,
)
from utils.control_center_v20_meta import (
    HELP_CATEGORY_ORDER, _all_help_commands, _command_description, _help_category,
    _permission_from_checks, _search_help,
)
from utils.control_center_v20_state import (
    _help_category_embed, _help_detail_embed, _help_home_embed, _home_embed, _setup_embed,
)
from cogs.control_center_setup_v20 import SetupControlView


class HelpCategorySelect(discord.ui.Select):
    def __init__(self, parent: "HelpControlView"):
        self.parent = parent
        counts = {category: 0 for category in HELP_CATEGORY_ORDER}
        for command in _all_help_commands(parent.bot):
            category = _help_category(command)
            counts[category] = counts.get(category, 0) + 1
        super().__init__(
            placeholder="Choisir une catégorie",
            options=[
                discord.SelectOption(
                    label=category,
                    value=category,
                    description=f"{counts.get(category, 0)} commande(s)",
                )
                for category in HELP_CATEGORY_ORDER if counts.get(category, 0)
            ],
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.parent.author_id:
            return await interaction.response.send_message(
                embed=embeds.error("Ce panneau appartient à une autre personne."),
                ephemeral=True,
            )
        self.parent.category = self.values[0]
        self.parent.page = 0
        self.parent.sync_buttons()
        panel, _ = _help_category_embed(
            self.parent.bot, self.parent.category, self.parent.prefix, self.parent.page
        )
        await interaction.response.edit_message(embed=panel, view=self.parent)


class HelpSearchModal(discord.ui.Modal, title="Rechercher une commande"):
    query = discord.ui.TextInput(
        label="Commande ou mot-clé",
        max_length=80,
        placeholder="ban, ticket, image, logs…",
    )

    def __init__(self, parent: "HelpControlView"):
        super().__init__()
        self.parent = parent

    async def on_submit(self, interaction: discord.Interaction):
        rows = _search_help(self.parent.bot, str(self.query.value))
        if not rows:
            return await interaction.response.send_message(
                embed=embeds.error("Aucune commande trouvée."), ephemeral=True
            )
        if len(rows) == 1:
            return await interaction.response.send_message(
                embed=_help_detail_embed(
                    self.parent.bot, rows[0], self.parent.prefix
                ),
                ephemeral=True,
            )
        text = "\n".join(
            f"`{self.parent.prefix}{command.qualified_name}` — "
            f"{_command_description(command)}"
            for command in rows[:10]
        )
        await interaction.response.send_message(
            embed=embeds.neutral("Résultats", text), ephemeral=True
        )


class HelpControlView(discord.ui.View):
    def __init__(self, bot: commands.Bot, author_id: int, prefix: str):
        super().__init__(timeout=300)
        self.bot = bot
        self.author_id = int(author_id)
        self.prefix = prefix
        self.category: str | None = None
        self.page = 0
        self.add_item(HelpCategorySelect(self))
        self.sync_buttons()

    def sync_buttons(self):
        self.previous.disabled = self.category is None or self.page <= 0
        if self.category is None:
            self.next.disabled = True
        else:
            _panel, pages = _help_category_embed(
                self.bot, self.category, self.prefix, self.page
            )
            self.next.disabled = self.page >= pages - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message(
            embed=embeds.error("Ce panneau appartient à une autre personne."),
            ephemeral=True,
        )
        return False

    @discord.ui.button(label="Rechercher", style=discord.ButtonStyle.secondary, row=1)
    async def search(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(HelpSearchModal(self))

    @discord.ui.button(label="Précédent", style=discord.ButtonStyle.secondary, row=2)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        self.sync_buttons()
        panel, _ = _help_category_embed(
            self.bot, self.category, self.prefix, self.page
        )
        await interaction.response.edit_message(embed=panel, view=self)

    @discord.ui.button(label="Accueil", style=discord.ButtonStyle.secondary, row=2)
    async def home(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.category = None
        self.page = 0
        self.sync_buttons()
        await interaction.response.edit_message(
            embed=_help_home_embed(self.bot), view=self
        )

    @discord.ui.button(label="Suivant", style=discord.ButtonStyle.secondary, row=2)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        self.sync_buttons()
        panel, _ = _help_category_embed(
            self.bot, self.category, self.prefix, self.page
        )
        await interaction.response.edit_message(embed=panel, view=self)


class SentriXControlCenterV20(commands.Cog, name="SentriXControlCenterV20"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(
        name="setup", description="Ouvrir le centre de configuration SentriX."
    )
    async def setup_command(self, ctx: commands.Context):
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            raise checks.BotPermissionError(
                "Cette commande doit être utilisée sur un serveur."
            )
        if not await _can_open_setup(self.bot, ctx.guild, ctx.author):
            raise checks.BotPermissionError(
                "Permission requise : **Administrateur**."
            )
        panel = await _home_embed(self.bot, ctx.guild)
        view = SetupControlView(
            self.bot, ctx.guild.id, ctx.author.id, ctx.channel.id
        )
        message = await ctx.send(embed=panel, view=view)
        view.message_id = message.id

    @commands.hybrid_command(
        name="help", aliases=["aide"],
        description="Trouver rapidement une commande SentriX."
    )
    @app_commands.describe(commande="Nom ou mot-clé de la commande")
    async def help_command(
        self, ctx: commands.Context, *, commande: str | None = None
    ):
        prefix = str(getattr(ctx, "clean_prefix", None) or "+")
        if commande:
            rows = _search_help(self.bot, commande)
            query = commande.casefold()
            exact = next(
                (
                    command for command in rows
                    if query in {
                        command.name.casefold(),
                        command.qualified_name.casefold(),
                        *(alias.casefold() for alias in (command.aliases or [])),
                    }
                ),
                None,
            )
            if exact:
                return await ctx.send(
                    embed=_help_detail_embed(self.bot, exact, prefix)
                )
            if not rows:
                return await ctx.send(
                    embed=embeds.error(
                        f"Aucune commande trouvée pour `{commande}`."
                    )
                )
            text = "\n\n".join(
                f"`{prefix}{command.qualified_name}`\n"
                f"{_command_description(command)}\n"
                f"Permission : {_permission_from_checks(command)}"
                for command in rows[:8]
            )
            return await ctx.send(
                embed=_setup_embed(
                    f"SentriX — Recherche : {commande[:40]}", text
                )
            )
        await ctx.send(
            embed=_help_home_embed(self.bot),
            view=HelpControlView(self.bot, ctx.author.id, prefix),
        )

    @commands.hybrid_command(
        name="config-view",
        description="Afficher le résumé de configuration du serveur."
    )
    async def safe_config_view(self, ctx: commands.Context):
        if ctx.guild is None:
            raise checks.BotPermissionError(
                "Cette commande doit être utilisée sur un serveur."
            )
        if not await _can_open_setup(self.bot, ctx.guild, ctx.author):
            raise checks.BotPermissionError(
                "Permission requise : **Administrateur**."
            )
        await ctx.send(embed=await _home_embed(self.bot, ctx.guild))

    @commands.hybrid_command(
        name="sentrix-manager-list",
        description="[Owner SentriX] Lister les gestionnaires globaux."
    )
    @checks.is_bot_owner()
    async def manager_list(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall(
            "SELECT * FROM global_bot_managers ORDER BY added_at"
        )
        text = "\n".join(
            f"<@{row['user_id']}> — ajouté <t:{row['added_at']}:R>"
            for row in rows
        ) or "Aucun gestionnaire global."
        await ctx.send(
            embed=embeds.neutral("Gestionnaires globaux SentriX", text)
        )

    @commands.hybrid_command(
        name="sentrix-manager-add",
        description="[Owner SentriX] Ajouter un gestionnaire global."
    )
    @checks.is_bot_owner()
    async def manager_add(self, ctx: commands.Context, membre: discord.User):
        await self.bot.db.execute(
            "INSERT INTO global_bot_managers (user_id, added_by, added_at) "
            "VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET "
            "added_by=excluded.added_by, added_at=excluded.added_at",
            (membre.id, ctx.author.id, int(time.time())),
        )
        await ctx.send(
            embed=embeds.success(
                f"{membre.mention} est maintenant gestionnaire global SentriX."
            )
        )

    @commands.hybrid_command(
        name="sentrix-manager-remove",
        description="[Owner SentriX] Retirer un gestionnaire global."
    )
    @checks.is_bot_owner()
    async def manager_remove(self, ctx: commands.Context, membre: discord.User):
        await self.bot.db.execute(
            "DELETE FROM global_bot_managers WHERE user_id = ?", (membre.id,)
        )
        await ctx.send(
            embed=embeds.success(
                f"{membre.mention} n’est plus gestionnaire global SentriX."
            )
        )


async def _remove_command(bot: commands.Bot, name: str):
    command = bot.get_command(name)
    if command is not None:
        bot.remove_command(command.name)
    if bot.tree.get_command(
        name, type=discord.AppCommandType.chat_input
    ) is not None:
        bot.tree.remove_command(name, type=discord.AppCommandType.chat_input)


def _harden_legacy_setup() -> None:
    """Neutralise l’ancienne page Gestionnaires, même sur les vieux panels persistants."""
    try:
        from cogs import configuration
    except Exception:
        return

    steps = getattr(configuration, "SETUP_STEPS", None)
    if isinstance(steps, list):
        steps[:] = [step for step in steps if step.get("key") != "managers"]

    configuration_cog = getattr(configuration, "Configuration", None)
    if configuration_cog is None:
        return

    async def strict_old_can_use_setup(
        self, interaction: discord.Interaction, author_id: int, guild_id: int
    ) -> bool:
        guild = interaction.guild
        if (
            guild is not None
            and guild.id == int(guild_id)
            and await _can_open_setup(self.bot, guild, interaction.user)
        ):
            return True
        if not interaction.response.is_done():
            await interaction.response.send_message(
                embed=embeds.error("Permission requise : **Administrateur**."),
                ephemeral=True,
            )
        return False

    configuration_cog._can_use_setup = strict_old_can_use_setup


async def setup(bot: commands.Bot):
    await _install_global_manager_table(bot)

    owner_commands = frozenset({
        "sentrix-manager-list", "sentrix-manager-add", "sentrix-manager-remove",
    })
    bot_main.OWNER_ONLY_COMMANDS = bot_main.OWNER_ONLY_COMMANDS | owner_commands
    bot_main.KNOWN_PERMISSION_COMMANDS = (
        bot_main.KNOWN_PERMISSION_COMMANDS | owner_commands
    )

    _harden_legacy_setup()
    _install_strict_permission_policy(bot)
    for name in ("setup", "help", "config-view"):
        await _remove_command(bot, name)
    await bot.add_cog(SentriXControlCenterV20(bot))
