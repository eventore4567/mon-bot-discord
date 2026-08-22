"""Centres visuels V5 : statut, à-propos, thèmes, cartes et icônes de serveur."""
from __future__ import annotations

import asyncio
import functools
import time
from pathlib import Path

import discord
from discord.ext import commands

from database.db import PRIMARY_CREATOR_DISPLAY_NAME
from utils import checks, premium_style, stats_service, visual_v5


VERSION = "5.0"
ICON_CATEGORIES = (
    "security", "moderation", "tickets", "economy", "levels", "music",
    "games", "events", "invites", "ai", "configuration", "leaderboard",
)


def _avatar(bot: commands.Bot) -> str | None:
    user = getattr(bot, "user", None)
    url = getattr(getattr(user, "display_avatar", None), "url", None)
    return str(url) if url else None


def _base(bot: commands.Bot, title: str, description: str = "", colour: int = 0x6C5CE7) -> discord.Embed:
    embed = discord.Embed(title=f"SentriX • {title}", description=description or None, colour=discord.Colour(colour))
    avatar = _avatar(bot)
    if avatar:
        embed.set_author(name="SentriX", icon_url=avatar)
    else:
        embed.set_author(name="SentriX")
    embed.set_footer(text=f"SentriX • V{VERSION}")
    return embed


async def build_status_embed(bot: commands.Bot, guild: discord.Guild | None) -> discord.Embed:
    latency = max(0, round(float(bot.latency) * 1000))
    database_ok = False
    try:
        row = await bot.db.fetchone("SELECT 1 AS ok")
        database_ok = bool(row and row["ok"] == 1)
    except Exception:
        pass
    ai_ok = bot.get_cog("Ai") is not None
    music_ok = bot.get_cog("Music") is not None
    online = sum(1 for item in (database_ok, ai_ok, music_ok) if item)
    colour = 0x2FBF71 if online == 3 and latency < 300 else 0xF0B232
    embed = _base(
        bot,
        "Statut",
        "État en direct des services principaux. Utilise **Actualiser** pour refaire le contrôle.",
        colour,
    )
    embed.add_field(name="Discord", value=f"En ligne • {latency} ms", inline=True)
    embed.add_field(name="Base", value="Opérationnelle" if database_ok else "Indisponible", inline=True)
    embed.add_field(name="Services", value=f"{online}/3 opérationnels", inline=True)
    embed.add_field(name="IA", value="Disponible" if ai_ok else "Indisponible", inline=True)
    embed.add_field(name="Musique", value="Disponible" if music_ok else "Indisponible", inline=True)
    embed.add_field(name="Commandes", value=str(len(bot.commands)), inline=True)
    embed.set_footer(text=f"SentriX • Actualisé <t:{int(time.time())}:R>")
    return embed


def build_about_embed(bot: commands.Bot) -> discord.Embed:
    members = sum(int(guild.member_count or 0) for guild in bot.guilds)
    embed = _base(
        bot,
        "À propos",
        "Assistant complet pour protéger, configurer et animer une communauté Discord.",
    )
    embed.add_field(name="Version", value=f"V{VERSION} • Expérience visuelle", inline=True)
    embed.add_field(name="Créateur", value=PRIMARY_CREATOR_DISPLAY_NAME, inline=True)
    embed.add_field(name="Serveurs", value=premium_style.format_number(len(bot.guilds)), inline=True)
    embed.add_field(name="Membres", value=premium_style.format_number(members), inline=True)
    embed.add_field(name="Commandes", value=premium_style.format_number(len(bot.commands)), inline=True)
    embed.add_field(name="Interface", value="Texte + slash • Mobile", inline=True)
    avatar = _avatar(bot)
    if avatar:
        embed.set_thumbnail(url=avatar)
    return embed


def build_updates_embed(bot: commands.Bot) -> discord.Embed:
    embed = _base(bot, "Nouveautés", "Les changements visibles les plus récents.")
    embed.add_field(
        name="V5 • Identité",
        value="Thèmes serveur, carte de profil, icônes SentriX et accueil personnalisé.",
        inline=False,
    )
    embed.add_field(
        name="V5 • Interfaces",
        value="Centre de statut, boutons actifs, actualisation, fermeture et états vides guidés.",
        inline=False,
    )
    embed.add_field(
        name="V4 • Compact",
        value="Aide, configuration, boutique, profil et file musicale optimisés pour mobile.",
        inline=False,
    )
    return embed


class StatusHubView(discord.ui.View):
    def __init__(self, bot: commands.Bot, guild: discord.Guild | None, owner_id: int, page: str = "status"):
        super().__init__(timeout=180)
        self.bot = bot
        self.guild = guild
        self.owner_id = int(owner_id)
        self.message: discord.Message | None = None
        self._set_active(page)

    def _set_active(self, page: str):
        for item in self.children:
            if isinstance(item, discord.ui.Button) and item.custom_id:
                item.style = discord.ButtonStyle.primary if item.custom_id == f"sx:v5:{page}" else discord.ButtonStyle.secondary
                if item.custom_id == "sx:v5:close":
                    item.style = discord.ButtonStyle.danger

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message("Ouvre ton propre panneau avec `+status`.", ephemeral=True)
        return False

    @discord.ui.button(label="Statut", custom_id="sx:v5:status")
    async def status(self, interaction: discord.Interaction, _button: discord.ui.Button):
        self._set_active("status")
        await interaction.response.edit_message(embed=await build_status_embed(self.bot, self.guild), view=self)

    @discord.ui.button(label="À propos", custom_id="sx:v5:about")
    async def about(self, interaction: discord.Interaction, _button: discord.ui.Button):
        self._set_active("about")
        await interaction.response.edit_message(embed=build_about_embed(self.bot), view=self)

    @discord.ui.button(label="Nouveautés", custom_id="sx:v5:updates")
    async def updates(self, interaction: discord.Interaction, _button: discord.ui.Button):
        self._set_active("updates")
        await interaction.response.edit_message(embed=build_updates_embed(self.bot), view=self)

    @discord.ui.button(label="Fermer", style=discord.ButtonStyle.danger, custom_id="sx:v5:close")
    async def close(self, interaction: discord.Interaction, _button: discord.ui.Button):
        try:
            await interaction.response.defer()
            await interaction.message.delete()
        except discord.HTTPException:
            if not interaction.response.is_done():
                await interaction.response.edit_message(view=None)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class ThemeSelect(discord.ui.Select):
    def __init__(self, view: "ThemeView", current: str):
        self.view_ref = view
        options = [
            discord.SelectOption(
                label=data["label"],
                value=key,
                description=data["description"],
                default=key == current,
            )
            for key, data in visual_v5.THEME_PRESETS.items()
        ]
        super().__init__(placeholder="Choisir un thème visuel…", options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        key = self.values[0]
        self.view_ref.current = key
        await self.view_ref.bot.db.set_design_settings(
            self.view_ref.guild.id,
            visual_v5.theme_settings(key, compact_mode=self.view_ref.compact),
        )
        self.view_ref.rebuild()
        await interaction.response.edit_message(embed=self.view_ref.embed(saved=True), view=self.view_ref)


class ThemeView(discord.ui.View):
    def __init__(self, bot: commands.Bot, guild: discord.Guild, owner_id: int, settings: dict):
        super().__init__(timeout=240)
        self.bot = bot
        self.guild = guild
        self.owner_id = int(owner_id)
        self.current = visual_v5.resolve_theme(settings.get("theme_preset")) or "sentrix"
        self.compact = bool(settings.get("compact_mode", False))
        self.seasonal = bool(settings.get("seasonal_theme", True))
        self.message: discord.Message | None = None
        self.rebuild()

    def rebuild(self):
        self.clear_items()
        self.add_item(ThemeSelect(self, self.current))
        compact = discord.ui.Button(label=f"Mode : {'Compact' if self.compact else 'Détaillé'}", style=discord.ButtonStyle.primary, row=1)
        seasonal = discord.ui.Button(label=f"Saisons : {'Actif' if self.seasonal else 'Inactif'}", style=discord.ButtonStyle.secondary, row=1)
        close = discord.ui.Button(label="Fermer", style=discord.ButtonStyle.danger, row=1)
        compact.callback = self.toggle_compact
        seasonal.callback = self.toggle_seasonal
        close.callback = self.close
        self.add_item(compact)
        self.add_item(seasonal)
        self.add_item(close)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id or interaction.user.guild_permissions.manage_guild:
            return True
        await interaction.response.send_message("Ce panneau est réservé au staff.", ephemeral=True)
        return False

    def embed(self, *, saved: bool = False) -> discord.Embed:
        data = visual_v5.THEME_PRESETS[self.current]
        embed = _base(
            self.bot,
            "Thèmes",
            f"**{data['label']}**\n{data['description']}\n\nLes changements s’appliquent aux nouveaux panneaux.",
            data["primary_color"],
        )
        embed.add_field(name="Affichage", value="Compact" if self.compact else "Détaillé", inline=True)
        embed.add_field(name="Thème saisonnier", value="Activé" if self.seasonal else "Désactivé", inline=True)
        if saved:
            embed.set_footer(text="SentriX • Thème enregistré")
        return embed

    async def toggle_compact(self, interaction: discord.Interaction):
        self.compact = not self.compact
        await self.bot.db.set_design_settings(self.guild.id, {"compact_mode": self.compact})
        self.rebuild()
        await interaction.response.edit_message(embed=self.embed(saved=True), view=self)

    async def toggle_seasonal(self, interaction: discord.Interaction):
        self.seasonal = not self.seasonal
        await self.bot.db.set_design_settings(self.guild.id, {"seasonal_theme": self.seasonal})
        self.rebuild()
        await interaction.response.edit_message(embed=self.embed(saved=True), view=self)

    async def close(self, interaction: discord.Interaction):
        await interaction.response.edit_message(view=None)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class VisualExperienceV5(commands.Cog, name="VisualExperienceV5"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self._patch_status()
        self._patch_changelog()

    def _patch_status(self):
        """Habille la commande historique +bot-status (et son alias +status).

        La couche ``common_command_names`` crée déjà l'alias ``status`` pour
        ``bot-status`` avant le chargement de cette extension. Déclarer une deuxième
        commande nommée ``status`` faisait donc échouer ``add_cog`` : Discord.py
        rejetait le doublon et *toutes* les commandes V5 (+iconsetup,
        +design-theme, +profile-card, +about) disparaissaient avec lui.

        On conserve une seule commande canonique et on remplace uniquement son rendu.
        L'ancien nom +bot-status et le nom court +status continuent ainsi de fonctionner.
        """
        command = self.bot.get_command("bot-status")
        if command is None or getattr(command, "_sentrix_v5_status", False):
            return

        original_params = command.params.copy()

        async def callback(_cog, ctx: commands.Context):
            view = StatusHubView(self.bot, ctx.guild, ctx.author.id, "status")
            message = await ctx.send(embed=await build_status_embed(self.bot, ctx.guild), view=view)
            view.message = message

        command.callback = functools.wraps(command.callback)(callback)
        command.params = original_params
        command._sentrix_v5_status = True

    def _patch_changelog(self):
        command = self.bot.get_command("changelog")
        if command is None or getattr(command, "_sentrix_v5_changelog", False):
            return

        original_params = command.params.copy()

        async def callback(_cog, ctx: commands.Context):
            view = StatusHubView(self.bot, ctx.guild, ctx.author.id, "updates")
            message = await ctx.send(embed=build_updates_embed(self.bot), view=view)
            view.message = message

        command.callback = functools.wraps(command.callback)(callback)
        command.params = original_params
        command._sentrix_v5_changelog = True

    @commands.command(name="about")
    async def about_command(self, ctx: commands.Context):
        view = StatusHubView(self.bot, ctx.guild, ctx.author.id, "about")
        message = await ctx.send(embed=build_about_embed(self.bot), view=view)
        view.message = message

    @commands.command(name="design-theme", aliases=["theme-design"])
    @commands.guild_only()
    @checks.is_owner_or_admin_for("configuration")
    async def design_theme(self, ctx: commands.Context, preset: str | None = None):
        settings = await self.bot.db.get_design_settings(ctx.guild.id)
        resolved = visual_v5.resolve_theme(preset) if preset else None
        if preset and resolved is None:
            choices = ", ".join(visual_v5.THEME_PRESETS)
            return await ctx.send(embed=_base(self.bot, "Thème introuvable", f"Choix disponibles : `{choices}`.", 0xED4245))
        if resolved:
            settings = await self.bot.db.set_design_settings(ctx.guild.id, visual_v5.theme_settings(resolved))
        view = ThemeView(self.bot, ctx.guild, ctx.author.id, settings)
        message = await ctx.send(embed=view.embed(saved=bool(resolved)), view=view)
        view.message = message

    @commands.command(name="profile-card", aliases=["card"])
    @commands.guild_only()
    async def profile_card(self, ctx: commands.Context, member: discord.Member | None = None):
        member = member or ctx.author
        loading = _base(self.bot, "Carte de profil", "Préparation de la carte.")
        message = await ctx.send(embed=loading)
        task = asyncio.create_task(self._render_profile(ctx.guild, member))
        for step in ("Préparation de la carte..", "Préparation de la carte..."):
            await asyncio.sleep(0.35)
            if task.done():
                break
            loading.description = step
            try:
                await message.edit(embed=loading)
            except discord.HTTPException:
                pass
        try:
            buffer = await task
            file = discord.File(buffer, filename="sentrix-profile.png")
            embed = _base(self.bot, "Carte de profil", f"Profil de **{member.display_name}**")
            embed.set_image(url="attachment://sentrix-profile.png")
            await message.edit(embed=embed, attachments=[file])
        except Exception:
            await message.edit(embed=_base(self.bot, "Carte indisponible", "Impossible de générer la carte maintenant. Réessaie dans quelques instants.", 0xED4245))

    async def _render_profile(self, guild: discord.Guild, member: discord.Member):
        stats = await stats_service.get_member_statistics(self.bot, guild, member)
        settings = await self.bot.db.get_design_settings(guild.id)
        return await visual_v5.render_member_card(member, guild, stats, settings)

    @commands.command(name="iconsetup", aliases=["icons-setup"])
    @commands.guild_only()
    @checks.is_owner_or_admin_for("configuration")
    async def iconsetup(self, ctx: commands.Context, category: str = "all"):
        """Installe les petites icônes SentriX comme emojis personnalisés du serveur."""
        if not ctx.guild.me.guild_permissions.manage_emojis_and_stickers:
            return await ctx.send(embed=_base(self.bot, "Permission requise", "Donne au bot la permission **Gérer les expressions**.", 0xED4245))
        selected = list(ICON_CATEGORIES) if category.casefold() == "all" else [category.casefold()]
        selected = [item for item in selected if item in ICON_CATEGORIES]
        if not selected:
            return await ctx.send(embed=_base(self.bot, "Catégorie inconnue", f"Choisis : `{', '.join(ICON_CATEGORIES)}` ou `all`."))

        existing = {emoji.name for emoji in ctx.guild.emojis}
        created, skipped, failed = [], [], []
        progress = await ctx.send(embed=_base(self.bot, "Icônes", f"Installation de {len(selected)} icône(s)…"))
        for name in selected:
            emoji_name = f"sx_{name}"
            if emoji_name in existing:
                skipped.append(name)
                continue
            path = Path(visual_v5.ASSET_DIR) / f"{name}.png"
            try:
                data = await asyncio.to_thread(path.read_bytes)
                await ctx.guild.create_custom_emoji(name=emoji_name, image=data, reason="Pack visuel SentriX V5")
                created.append(name)
            except (OSError, discord.HTTPException):
                failed.append(name)
        lines = [
            f"Créées : **{len(created)}**",
            f"Déjà présentes : **{len(skipped)}**",
            f"Échecs : **{len(failed)}**",
        ]
        if failed:
            lines.append("À réessayer : " + ", ".join(failed))
        await progress.edit(embed=_base(self.bot, "Icônes installées", "\n".join(lines), 0x2FBF71 if not failed else 0xF0B232))


async def setup(bot: commands.Bot):
    await bot.add_cog(VisualExperienceV5(bot))

    # Diagnostic explicite : le démarrage général du bot tolère l'échec d'une extension.
    # Cette vérification rend immédiatement visible dans les logs toute régression du
    # catalogue au lieu de laisser Railway afficher un déploiement sain avec des commandes
    # silencieusement absentes.
    required = ("status", "about", "design-theme", "profile-card", "iconsetup")
    missing = [name for name in required if bot.get_command(name) is None]
    if missing:
        raise RuntimeError("Commandes V5 non enregistrées : " + ", ".join(missing))
