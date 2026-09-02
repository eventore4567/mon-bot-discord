"""
Cog PANNEAU STAFF DES MINI-JEUX — +gamesetup (Partie 1 de la demande de Jayden — Phase 4).

Panneau interactif (comme +logsetup, voir cogs/configuration.py::LogsSetupView, même
convention de code : select.callback = closure, ChannelSelect/RoleSelect, verrouillage à
l'auteur, désactivation des boutons au timeout) pour configurer utils/game_rewards.py par
serveur : activer/désactiver le système, désactiver des jeux précis, restreindre à des
salons/rôles, limite journalière, multiplicateur d'événement, bornes min/max de récompense,
logs, classement, DMs, mode compact, difficulté par défaut. Toutes les données sont lues et
écrites via Database.get_game_settings/set_game_settings (table game_settings), TOUJOURS
filtrées par guild_id — jamais de fuite entre serveurs.
"""

import discord
from discord.ext import commands

from utils import embeds, checks, game_rewards
from utils import sentrix_panels as panels
from cogs.games_economy import GAME_CATALOG

CATEGORY_LABELS = {"rapide": "Rapides", "duel": "Duels", "communautaire": "Communautaires", "solo": "Solo"}


class GamesSetup(commands.Cog, name="GamesSetup"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _build_home(self, guild_id: int) -> tuple[discord.Embed, "GamesSetupView"]:
        settings = await game_rewards.get_settings(self.bot, guild_id)
        e = embeds.neutral("🎮 Configuration des mini-jeux")
        e.add_field(name="Système", value="🟢 Activé" if settings["enabled"] else "🔴 Désactivé", inline=True)
        e.add_field(name="Jeux désactivés", value=str(len(settings["disabled_games"])) or "0", inline=True)
        e.add_field(name="Limite journalière", value=str(settings["daily_limit"]) if settings["daily_limit"] > 0 else "Illimitée", inline=True)
        e.add_field(name="Multiplicateur d'évènement", value=f"x{settings['event_multiplier']}", inline=True)
        e.add_field(name="Récompense min/max", value=f"x{settings['min_reward_multiplier']} → x{settings['max_reward_multiplier']}", inline=True)
        e.add_field(name="Salons", value=f"{len(settings['allowed_channel_ids'])} autorisé(s), {len(settings['blocked_channel_ids'])} bloqué(s)", inline=True)
        e.add_field(name="Rôles", value=f"{len(settings['allowed_role_ids'])} autorisé(s), {len(settings['blocked_role_ids'])} bloqué(s)", inline=True)
        e.add_field(
            name="Affichage",
            value=(
                f"Logs : {'✅' if settings['logs_enabled'] else '❌'} • "
                f"Classement : {'✅' if settings['leaderboard_enabled'] else '❌'} • "
                f"DMs : {'✅' if settings['dm_results'] else '❌'} • "
                f"Compact : {'✅' if settings['compact_mode'] else '❌'} • "
                f"Difficulté : {settings['default_difficulty']}"
            ),
            inline=False,
        )
        view = GamesSetupView(self, author_id=None, guild_id=guild_id)
        return e, view

    @commands.hybrid_command(name="gamesetup", description="Panneau staff de configuration des mini-jeux.", with_app_command=False)
    @checks.is_owner_or_admin_for("economie")
    async def gamesetup(self, ctx: commands.Context):
        e, view = await self._build_home(ctx.guild.id)
        view.author_id = ctx.author.id
        msg = await panels.envoyer(ctx, panels.avec_composants(panels.depuis_embed(e), view))
        view.message = msg


class GamesSetupView(discord.ui.View):
    def __init__(self, cog: GamesSetup, *, author_id: int | None, guild_id: int, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.author_id = author_id
        self.guild_id = guild_id
        self.section: str | None = None
        self.message: discord.Message | None = None
        self._render_home()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.author_id is not None and interaction.user.id != self.author_id:
            await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error("Vous n'êtes pas autorisé à utiliser ce panneau.")), ephemere=True)
            return False
        return True

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass

    # ---------------------------------------------------------------- ACCUEIL

    def _render_home(self):
        self.clear_items()
        options = [
            discord.SelectOption(label="⚙️ Général", value="general", description="Activer/désactiver, limite journalière, multiplicateurs"),
            discord.SelectOption(label="🚫 Jeux — Rapides", value="games_rapide", description="Activer/désactiver les jeux rapides"),
            discord.SelectOption(label="🚫 Jeux — Duels", value="games_duel", description="Activer/désactiver les duels"),
            discord.SelectOption(label="🚫 Jeux — Communautaires", value="games_communautaire", description="Activer/désactiver les jeux communautaires"),
            discord.SelectOption(label="🚫 Jeux — Solo", value="games_solo", description="Activer/désactiver les jeux solo"),
            discord.SelectOption(label="📁 Salons", value="channels", description="Restreindre à/exclure certains salons"),
            discord.SelectOption(label="👥 Rôles", value="roles", description="Restreindre à/exclure certains rôles"),
            discord.SelectOption(label="🖥️ Affichage", value="display", description="Logs, classement, DMs, mode compact, difficulté"),
        ]
        select = discord.ui.Select(placeholder="📂 Choisir une section...", options=options, row=0)
        select.callback = self._make_section_callback(select)
        self.add_item(select)
        close_btn = discord.ui.Button(label="Fermer", style=discord.ButtonStyle.secondary, emoji="❌", row=1)
        close_btn.callback = self._close_clicked
        self.add_item(close_btn)

    def _make_section_callback(self, select: discord.ui.Select):
        async def callback(interaction: discord.Interaction):
            self.section = select.values[0]
            await self._refresh(interaction)
        return callback

    async def _close_clicked(self, interaction: discord.Interaction):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()

    async def _back_clicked(self, interaction: discord.Interaction):
        self.section = None
        self._render_home()
        e, _ = await self.cog._build_home(self.guild_id)
        await interaction.response.edit_message(embed=e, view=self)

    async def _refresh(self, interaction: discord.Interaction):
        e = await self._render_section(interaction.guild)
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=e, view=self)
        else:
            await interaction.response.edit_message(embed=e, view=self)

    async def _render_section(self, guild: discord.Guild) -> discord.Embed:
        if self.section == "general":
            return await self._render_general(guild)
        if self.section and self.section.startswith("games_"):
            return await self._render_games(guild, self.section.split("_", 1)[1])
        if self.section == "channels":
            return await self._render_channels(guild)
        if self.section == "roles":
            return await self._render_roles(guild)
        if self.section == "display":
            return await self._render_display(guild)
        e, _ = await self.cog._build_home(self.guild_id)
        return e

    # ---------------------------------------------------------------- GÉNÉRAL

    async def _render_general(self, guild: discord.Guild) -> discord.Embed:
        self.clear_items()
        settings = await game_rewards.get_settings(self.cog.bot, guild.id)
        e = embeds.neutral("⚙️ Réglages généraux")
        e.add_field(name="Système", value="🟢 Activé" if settings["enabled"] else "🔴 Désactivé", inline=True)
        e.add_field(name="Limite journalière", value=str(settings["daily_limit"]) if settings["daily_limit"] > 0 else "Illimitée", inline=True)
        e.add_field(name="Multiplicateur d'évènement", value=f"x{settings['event_multiplier']}", inline=True)
        e.add_field(name="Récompense min/max", value=f"x{settings['min_reward_multiplier']} → x{settings['max_reward_multiplier']}", inline=True)

        toggle_btn = discord.ui.Button(
            label="Désactiver tous les jeux" if settings["enabled"] else "Activer tous les jeux",
            style=discord.ButtonStyle.danger if settings["enabled"] else discord.ButtonStyle.success,
            emoji="🔴" if settings["enabled"] else "🟢", row=0,
        )
        toggle_btn.callback = self._toggle_enabled
        self.add_item(toggle_btn)

        edit_btn = discord.ui.Button(label="Modifier les valeurs", style=discord.ButtonStyle.primary, emoji="✏️", row=0)
        edit_btn.callback = self._open_general_modal
        self.add_item(edit_btn)

        back_btn = discord.ui.Button(label="Retour", style=discord.ButtonStyle.secondary, emoji="◀", row=1)
        back_btn.callback = self._back_clicked
        self.add_item(back_btn)
        return e

    async def _toggle_enabled(self, interaction: discord.Interaction):
        settings = await game_rewards.get_settings(self.cog.bot, interaction.guild.id)
        await game_rewards.set_settings(self.cog.bot, interaction.guild.id, {"enabled": not settings["enabled"]})
        await self._refresh(interaction)

    async def _open_general_modal(self, interaction: discord.Interaction):
        settings = await game_rewards.get_settings(self.cog.bot, interaction.guild.id)
        await interaction.response.send_modal(GeneralSettingsModal(self, settings))

    # ---------------------------------------------------------------- JEUX DÉSACTIVÉS

    async def _render_games(self, guild: discord.Guild, category: str) -> discord.Embed:
        self.clear_items()
        settings = await game_rewards.get_settings(self.cog.bot, guild.id)
        disabled = set(settings["disabled_games"])
        games_in_category = [name for name, (label, cat) in GAME_CATALOG.items() if cat == category]

        e = embeds.neutral(f"🚫 Jeux désactivés — {CATEGORY_LABELS.get(category, category)}")
        active = [n for n in games_in_category if n not in disabled]
        inactive = [n for n in games_in_category if n in disabled]
        e.add_field(name="Activés", value="\n".join(f"🟢 {GAME_CATALOG[n][0]}" for n in active) or "Aucun", inline=True)
        e.add_field(name="Désactivés", value="\n".join(f"🔴 {GAME_CATALOG[n][0]}" for n in inactive) or "Aucun", inline=True)

        options = [
            discord.SelectOption(label=GAME_CATALOG[n][0][:100], value=n, default=(n in disabled))
            for n in games_in_category
        ]
        select = discord.ui.Select(
            placeholder="Cocher = désactivé", options=options, min_values=0, max_values=len(options), row=0,
        )
        select.callback = self._make_games_callback(select, category, games_in_category)
        self.add_item(select)

        back_btn = discord.ui.Button(label="Retour", style=discord.ButtonStyle.secondary, emoji="◀", row=1)
        back_btn.callback = self._back_clicked
        self.add_item(back_btn)
        return e

    def _make_games_callback(self, select: discord.ui.Select, category: str, games_in_category: list):
        async def callback(interaction: discord.Interaction):
            settings = await game_rewards.get_settings(self.cog.bot, interaction.guild.id)
            disabled = set(settings["disabled_games"])
            disabled -= set(games_in_category)  # on repart de zéro pour CETTE catégorie
            disabled |= set(select.values)
            await game_rewards.set_settings(self.cog.bot, interaction.guild.id, {"disabled_games": sorted(disabled)})
            self.section = f"games_{category}"
            await self._refresh(interaction)
        return callback

    # ---------------------------------------------------------------- SALONS

    async def _render_channels(self, guild: discord.Guild) -> discord.Embed:
        self.clear_items()
        settings = await game_rewards.get_settings(self.cog.bot, guild.id)
        allowed = [guild.get_channel(cid) for cid in settings["allowed_channel_ids"]]
        blocked = [guild.get_channel(cid) for cid in settings["blocked_channel_ids"]]
        e = embeds.neutral("📁 Salons")
        e.add_field(name="Autorisés (liste vide = partout)", value="\n".join(c.mention for c in allowed if c) or "Aucun", inline=False)
        e.add_field(name="Bloqués", value="\n".join(c.mention for c in blocked if c) or "Aucun", inline=False)

        allowed_select = discord.ui.ChannelSelect(placeholder="📁 Définir les salons AUTORISÉS (remplace la liste)...", channel_types=[discord.ChannelType.text], max_values=25, row=0)
        allowed_select.callback = self._make_channel_callback(allowed_select, "allowed_channel_ids")
        self.add_item(allowed_select)

        blocked_select = discord.ui.ChannelSelect(placeholder="📁 Définir les salons BLOQUÉS (remplace la liste)...", channel_types=[discord.ChannelType.text], max_values=25, row=1)
        blocked_select.callback = self._make_channel_callback(blocked_select, "blocked_channel_ids")
        self.add_item(blocked_select)

        reset_btn = discord.ui.Button(label="Réinitialiser", style=discord.ButtonStyle.danger, emoji="🗑️", row=2)
        reset_btn.callback = self._reset_channels
        self.add_item(reset_btn)
        back_btn = discord.ui.Button(label="Retour", style=discord.ButtonStyle.secondary, emoji="◀", row=2)
        back_btn.callback = self._back_clicked
        self.add_item(back_btn)
        return e

    def _make_channel_callback(self, select: discord.ui.ChannelSelect, field: str):
        async def callback(interaction: discord.Interaction):
            ids = [c.id for c in select.values]
            await game_rewards.set_settings(self.cog.bot, interaction.guild.id, {field: ids})
            self.section = "channels"
            await self._refresh(interaction)
        return callback

    async def _reset_channels(self, interaction: discord.Interaction):
        await game_rewards.set_settings(self.cog.bot, interaction.guild.id, {"allowed_channel_ids": [], "blocked_channel_ids": []})
        self.section = "channels"
        await self._refresh(interaction)

    # ---------------------------------------------------------------- RÔLES

    async def _render_roles(self, guild: discord.Guild) -> discord.Embed:
        self.clear_items()
        settings = await game_rewards.get_settings(self.cog.bot, guild.id)
        allowed = [guild.get_role(rid) for rid in settings["allowed_role_ids"]]
        blocked = [guild.get_role(rid) for rid in settings["blocked_role_ids"]]
        e = embeds.neutral("👥 Rôles")
        e.add_field(name="Autorisés (liste vide = tout le monde)", value="\n".join(r.mention for r in allowed if r) or "Aucun", inline=False)
        e.add_field(name="Bloqués", value="\n".join(r.mention for r in blocked if r) or "Aucun", inline=False)

        allowed_select = discord.ui.RoleSelect(placeholder="👥 Définir les rôles AUTORISÉS (remplace la liste)...", max_values=25, row=0)
        allowed_select.callback = self._make_role_callback(allowed_select, "allowed_role_ids")
        self.add_item(allowed_select)

        blocked_select = discord.ui.RoleSelect(placeholder="👥 Définir les rôles BLOQUÉS (remplace la liste)...", max_values=25, row=1)
        blocked_select.callback = self._make_role_callback(blocked_select, "blocked_role_ids")
        self.add_item(blocked_select)

        reset_btn = discord.ui.Button(label="Réinitialiser", style=discord.ButtonStyle.danger, emoji="🗑️", row=2)
        reset_btn.callback = self._reset_roles
        self.add_item(reset_btn)
        back_btn = discord.ui.Button(label="Retour", style=discord.ButtonStyle.secondary, emoji="◀", row=2)
        back_btn.callback = self._back_clicked
        self.add_item(back_btn)
        return e

    def _make_role_callback(self, select: discord.ui.RoleSelect, field: str):
        async def callback(interaction: discord.Interaction):
            ids = [r.id for r in select.values]
            await game_rewards.set_settings(self.cog.bot, interaction.guild.id, {field: ids})
            self.section = "roles"
            await self._refresh(interaction)
        return callback

    async def _reset_roles(self, interaction: discord.Interaction):
        await game_rewards.set_settings(self.cog.bot, interaction.guild.id, {"allowed_role_ids": [], "blocked_role_ids": []})
        self.section = "roles"
        await self._refresh(interaction)

    # ---------------------------------------------------------------- AFFICHAGE

    async def _render_display(self, guild: discord.Guild) -> discord.Embed:
        self.clear_items()
        settings = await game_rewards.get_settings(self.cog.bot, guild.id)
        e = embeds.neutral("🖥️ Affichage")
        e.add_field(name="Logs (+logsetup, catégorie Jeux)", value="✅ Activés" if settings["logs_enabled"] else "❌ Désactivés", inline=True)
        e.add_field(name="Classement (+gametop)", value="✅ Activé" if settings["leaderboard_enabled"] else "❌ Désactivé", inline=True)
        e.add_field(name="Résultats en DM", value="✅ Activés" if settings["dm_results"] else "❌ Désactivés", inline=True)
        e.add_field(name="Mode compact", value="✅ Activé" if settings["compact_mode"] else "❌ Désactivé", inline=True)
        e.add_field(name="Difficulté par défaut", value=settings["default_difficulty"], inline=True)

        self._add_display_toggle("logs_enabled", "Logs", settings["logs_enabled"], row=0)
        self._add_display_toggle("leaderboard_enabled", "Classement", settings["leaderboard_enabled"], row=0)
        self._add_display_toggle("dm_results", "DMs", settings["dm_results"], row=1)
        self._add_display_toggle("compact_mode", "Compact", settings["compact_mode"], row=1)

        diff_select = discord.ui.Select(
            placeholder="🎚️ Difficulté par défaut...",
            options=[discord.SelectOption(label=d.capitalize(), value=d, default=(d == settings["default_difficulty"])) for d in ("facile", "normal", "difficile")],
            row=2,
        )
        diff_select.callback = self._make_difficulty_callback(diff_select)
        self.add_item(diff_select)

        back_btn = discord.ui.Button(label="Retour", style=discord.ButtonStyle.secondary, emoji="◀", row=3)
        back_btn.callback = self._back_clicked
        self.add_item(back_btn)
        return e

    def _add_display_toggle(self, field: str, label: str, current: bool, row: int):
        btn = discord.ui.Button(
            label=f"{label} : {'ON' if current else 'OFF'}",
            style=discord.ButtonStyle.success if current else discord.ButtonStyle.secondary,
            row=row,
        )

        async def callback(interaction: discord.Interaction):
            settings = await game_rewards.get_settings(self.cog.bot, interaction.guild.id)
            await game_rewards.set_settings(self.cog.bot, interaction.guild.id, {field: not settings[field]})
            self.section = "display"
            await self._refresh(interaction)

        btn.callback = callback
        self.add_item(btn)

    def _make_difficulty_callback(self, select: discord.ui.Select):
        async def callback(interaction: discord.Interaction):
            await game_rewards.set_settings(self.cog.bot, interaction.guild.id, {"default_difficulty": select.values[0]})
            self.section = "display"
            await self._refresh(interaction)
        return callback


class GeneralSettingsModal(discord.ui.Modal, title="Réglages généraux des mini-jeux"):
    limite = discord.ui.TextInput(label="Limite journalière (0 = illimitée)", max_length=5)
    multiplicateur = discord.ui.TextInput(label="Multiplicateur d'évènement (ex: 1.0, 2.0)", max_length=6)
    mini = discord.ui.TextInput(label="Multiplicateur de récompense minimum", max_length=6)
    maxi = discord.ui.TextInput(label="Multiplicateur de récompense maximum", max_length=6)

    def __init__(self, outer: GamesSetupView, settings: dict):
        super().__init__()
        self.outer = outer
        self.limite.default = str(settings["daily_limit"])
        self.multiplicateur.default = str(settings["event_multiplier"])
        self.mini.default = str(settings["min_reward_multiplier"])
        self.maxi.default = str(settings["max_reward_multiplier"])

    async def on_submit(self, interaction: discord.Interaction):
        try:
            limite = int(str(self.limite.value).strip())
            multi = float(str(self.multiplicateur.value).strip())
            mini = float(str(self.mini.value).strip())
            maxi = float(str(self.maxi.value).strip())
            assert limite >= 0 and multi >= 0 and mini >= 0 and maxi >= 0
        except (ValueError, AssertionError):
            return await panels.envoyer(interaction.response, panels.depuis_embed(embeds.error('Valeurs invalides — entrez des nombres positifs.')), ephemere=True)
        await game_rewards.set_settings(self.outer.cog.bot, interaction.guild.id, {
            "daily_limit": limite, "event_multiplier": multi, "min_reward_multiplier": mini, "max_reward_multiplier": maxi,
        })
        self.outer.section = "general"
        e = await self.outer._render_section(interaction.guild)
        await interaction.response.edit_message(embed=e, view=self.outer)


async def setup(bot: commands.Bot):
    await bot.add_cog(GamesSetup(bot))
