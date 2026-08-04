"""
Cog NIVEAUX / COMMUNAUTÉ / STATISTIQUES.
/stats (+me) /level (+rank) /leaderboard-levels /set-level-role /remove-level-role
/level-roles /set-xp /add-xp /reset-levels /profile /set-bio /voice-time /statsconfig

Refonte complète (voir demande de Jayden) : TOUTES les commandes qui affichent des
statistiques d'un membre (/stats, /level, /profile, /leaderboard-levels, et les pages
du bouton "Classement") passent maintenant par utils/stats_service.get_member_statistics(),
une seule source de vérité. Il ne peut plus y avoir deux chiffres différents pour le
même membre entre deux commandes.
"""

import asyncio
import random
import time
import discord
from discord import app_commands
from discord.ext import commands

from utils import embeds, checks, stats_service
from database.db import now, DEFAULT_STATS_SETTINGS

XP_COOLDOWN_FALLBACK = 60
XP_MIN_FALLBACK, XP_MAX_FALLBACK = 10, 25

# Ré-exporté pour compatibilité (certaines parties du bot pourraient encore importer ce
# nom depuis cogs.levels) — pointe directement vers la fonction centrale.
xp_for_level = stats_service.xp_required_for_level


# =============================================================================
# Boutons de navigation sous /stats
# =============================================================================

class StatsView(discord.ui.View):
    """Vue à 4 boutons (Statistiques / Niveau / Économie / Classement) affichée sous
    /stats. Édite toujours le MÊME message (jamais de nouvel embed envoyé), n'accepte
    les clics que de l'auteur de la commande ou d'un membre du staff, répond de façon
    privée à tout le monde d'autre, et désactive ses boutons à l'expiration."""

    def __init__(self, cog: "Levels", guild: discord.Guild, member: discord.Member, author_id: int, timeout: float = 120):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.guild = guild
        self.member = member
        self.author_id = author_id
        self.message: discord.Message | None = None
        self._set_active("stats")

    def _set_active(self, page: str):
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.custom_id:
                child.disabled = child.custom_id == f"statsnav:{page}"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True
        is_staff = False
        if isinstance(interaction.user, discord.Member):
            is_staff = interaction.user.guild_permissions.administrator or await interaction.client.db.is_bot_manager(
                self.guild.id, interaction.user.id
            )
        from config import OWNER_IDS
        if interaction.user.id in OWNER_IDS:
            is_staff = True
        if is_staff:
            return True
        await interaction.response.send_message(
            "❌ Ce menu n'est pas pour vous — utilisez `/stats` de votre côté pour consulter vos propres statistiques.",
            ephemeral=True,
        )
        return False

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    @discord.ui.button(label="📊 Statistiques", style=discord.ButtonStyle.blurple, custom_id="statsnav:stats", row=0)
    async def btn_stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = await self.cog.build_stats_embed(self.guild, self.member)
        self._set_active("stats")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="📈 Niveau", style=discord.ButtonStyle.blurple, custom_id="statsnav:level", row=0)
    async def btn_level(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = await self.cog.build_level_embed(self.guild, self.member)
        self._set_active("level")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="💰 Économie", style=discord.ButtonStyle.blurple, custom_id="statsnav:eco", row=0)
    async def btn_economy(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = await self.cog.build_economy_embed(self.guild, self.member)
        self._set_active("eco")
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🏆 Classement", style=discord.ButtonStyle.blurple, custom_id="statsnav:rank", row=0)
    async def btn_leaderboard(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = await self.cog.build_ranks_embed(self.guild, self.member)
        self._set_active("rank")
        await interaction.response.edit_message(embed=embed, view=self)


# Le décorateur discord.ui.Button écrit sur des fonctions "nues" — ce qui précède les
# transforme automatiquement en callbacks liés à la classe, comportement standard de
# discord.py (voir discord.ui.View). Rien de spécial à faire de plus ici.


# =============================================================================
# Panneau de configuration +statsconfig (staff)
# =============================================================================

class StatsAppearanceModal(discord.ui.Modal, title="Apparence de /stats et /level"):
    def __init__(self, view: "StatsConfigView"):
        super().__init__()
        self.view_ref = view
        p = view.pending
        self.titre = discord.ui.TextInput(label="Titre de /stats", default=p["title_stats"], max_length=100, required=True)
        self.footer = discord.ui.TextInput(label="Texte du footer", default=p["footer"], max_length=100, required=True)
        self.couleur = discord.ui.TextInput(
            label="Couleur (hexadécimal, ex: 5865F2)", default=f"{p['color']:06X}", max_length=6, min_length=6, required=True
        )
        self.emoji_rempli = discord.ui.TextInput(label="Emoji case remplie", default=p["emoji_filled"], max_length=10, required=True)
        self.emoji_vide = discord.ui.TextInput(label="Emoji case vide", default=p["emoji_empty"], max_length=10, required=True)
        for item in (self.titre, self.footer, self.couleur, self.emoji_rempli, self.emoji_vide):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            color_value = int(str(self.couleur.value).strip().lstrip("#"), 16)
        except ValueError:
            return await interaction.response.send_message(
                embed=embeds.error("Couleur invalide — utilisez un code hexadécimal comme `5865F2`."), ephemeral=True
            )
        self.view_ref.pending.update({
            "title_stats": str(self.titre.value),
            "footer": str(self.footer.value),
            "color": color_value,
            "emoji_filled": str(self.emoji_rempli.value),
            "emoji_empty": str(self.emoji_vide.value),
        })
        await self.view_ref.refresh(interaction)


class StatsXPModal(discord.ui.Modal, title="Réglages de l'XP"):
    def __init__(self, view: "StatsConfigView"):
        super().__init__()
        self.view_ref = view
        p = view.pending
        self.cooldown = discord.ui.TextInput(label="Cooldown entre deux gains (secondes)", default=str(p["xp_cooldown"]), max_length=6)
        self.xp_min = discord.ui.TextInput(label="XP minimum par message", default=str(p["xp_min"]), max_length=6)
        self.xp_max = discord.ui.TextInput(label="XP maximum par message", default=str(p["xp_max"]), max_length=6)
        for item in (self.cooldown, self.xp_min, self.xp_max):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            cooldown = int(str(self.cooldown.value).strip())
            xp_min = int(str(self.xp_min.value).strip())
            xp_max = int(str(self.xp_max.value).strip())
        except ValueError:
            return await interaction.response.send_message(embed=embeds.error("Utilisez uniquement des nombres entiers."), ephemeral=True)
        if cooldown < 0 or xp_min < 0 or xp_max < 0:
            return await interaction.response.send_message(embed=embeds.error("Ces valeurs ne peuvent pas être négatives."), ephemeral=True)
        if xp_min > xp_max:
            return await interaction.response.send_message(embed=embeds.error("Le XP minimum ne peut pas dépasser le XP maximum."), ephemeral=True)
        self.view_ref.pending.update({"xp_cooldown": cooldown, "xp_min": xp_min, "xp_max": xp_max})
        await self.view_ref.refresh(interaction)


VISIBILITY_OPTIONS = [
    ("show_economy", "💰 Économie"),
    ("show_reputation", "⭐ Réputation"),
    ("show_voice", "🔊 Temps vocal"),
    ("show_messages", "💬 Messages"),
    ("show_join_date", "📅 Date d'arrivée"),
    ("show_next_role", "🎭 Prochain rôle"),
]


class VisibilitySelect(discord.ui.Select):
    def __init__(self, view: "StatsConfigView"):
        self.view_ref = view
        options = [
            discord.SelectOption(label=label, value=key, default=view.pending.get(key, True))
            for key, label in VISIBILITY_OPTIONS
        ]
        super().__init__(
            placeholder="Champs à afficher sur /stats (sélectionnez TOUS ceux à garder visibles)",
            min_values=0, max_values=len(options), options=options, row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        chosen = set(self.values)
        for key, _ in VISIBILITY_OPTIONS:
            self.view_ref.pending[key] = key in chosen
        await self.view_ref.refresh(interaction)


class BoolToggleButton(discord.ui.Button):
    def __init__(self, view: "StatsConfigView", key: str, label: str, row: int):
        self.view_ref = view
        self.key = key
        self.base_label = label
        super().__init__(style=discord.ButtonStyle.secondary, row=row)
        self._sync_label()

    def _sync_label(self):
        value = self.view_ref.pending.get(self.key, False)
        self.label = f"{self.base_label} : {'✅ Oui' if value else '❌ Non'}"

    async def callback(self, interaction: discord.Interaction):
        self.view_ref.pending[self.key] = not self.view_ref.pending.get(self.key, False)
        self._sync_label()
        await self.view_ref.refresh(interaction)


class ExcludedRolesSelect(discord.ui.RoleSelect):
    def __init__(self, view: "StatsConfigView"):
        self.view_ref = view
        current = [r for r in (view.guild.get_role(rid) for rid in view.pending.get("xp_excluded_role_ids", [])) if r]
        super().__init__(
            placeholder="Rôles qui ne gagnent JAMAIS d'XP (remplace la liste actuelle)",
            min_values=0, max_values=10, row=2, default_values=current,
        )

    async def callback(self, interaction: discord.Interaction):
        self.view_ref.pending["xp_excluded_role_ids"] = [r.id for r in self.values]
        await self.view_ref.refresh(interaction)


class DisabledChannelsSelect(discord.ui.ChannelSelect):
    def __init__(self, view: "StatsConfigView"):
        self.view_ref = view
        raw = view.pending.get("_xp_channel_disabled", "") or ""
        current = [c for c in (view.guild.get_channel(int(x)) for x in raw.split(",") if x.strip().isdigit()) if c]
        super().__init__(
            placeholder="Salons où l'XP est désactivé (remplace la liste actuelle)",
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            min_values=0, max_values=10, row=3, default_values=current,
        )

    async def callback(self, interaction: discord.Interaction):
        ids = ",".join(str(c.id) for c in self.values)
        self.view_ref.pending["_xp_channel_disabled"] = ids
        await self.view_ref.refresh(interaction)


class VoiceIgnoredChannelsSelect(discord.ui.ChannelSelect):
    def __init__(self, view: "StatsConfigView"):
        self.view_ref = view
        current = [c for c in (view.guild.get_channel(cid) for cid in view.pending.get("voice_ignored_channel_ids", [])) if c]
        super().__init__(
            placeholder="Salons vocaux ignorés pour le temps vocal (remplace la liste actuelle)",
            channel_types=[discord.ChannelType.voice, discord.ChannelType.stage_voice],
            min_values=0, max_values=10, row=2, default_values=current,
        )

    async def callback(self, interaction: discord.Interaction):
        self.view_ref.pending["voice_ignored_channel_ids"] = [c.id for c in self.values]
        await self.view_ref.refresh(interaction)


class StatsConfigCategorySelect(discord.ui.Select):
    def __init__(self, view: "StatsConfigView"):
        self.view_ref = view
        options = [
            discord.SelectOption(label="🎨 Apparence (couleur, titre, footer, emojis)", value="appearance"),
            discord.SelectOption(label="👁️ Visibilité des champs", value="visibility"),
            discord.SelectOption(label="✨ XP (cooldown, bornes, exclusions)", value="xp"),
            discord.SelectOption(label="🔊 Vocal (salons ignorés)", value="voice"),
        ]
        super().__init__(placeholder="Que voulez-vous configurer ?", options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        self.view_ref.category = self.values[0]
        self.view_ref.rebuild_items()
        await self.view_ref.refresh(interaction)


class StatsConfigView(discord.ui.View):
    """Panneau +statsconfig — un menu de catégorie, des contrôles contextuels, et
    Prévisualiser / Enregistrer / Réinitialiser / Annuler toujours visibles en bas."""

    def __init__(self, cog: "Levels", guild: discord.Guild, author_id: int, settings: dict, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.guild = guild
        self.author_id = author_id
        self.pending = dict(settings)
        self.pending["_xp_channel_disabled"] = ""  # rempli séparément via get_guild_config, voir refresh()
        self.category = "appearance"
        self.message: discord.Message | None = None
        self.rebuild_items()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message("❌ Seule la personne ayant ouvert ce panneau peut l'utiliser.", ephemeral=True)
        return False

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    def rebuild_items(self):
        self.clear_items()
        self.add_item(StatsConfigCategorySelect(self))
        if self.category == "appearance":
            self.add_item(discord.ui.Button(label="✏️ Modifier textes/couleur", style=discord.ButtonStyle.primary, row=1, custom_id="cfg:edit_appearance"))
            self.children[-1].callback = self._open_appearance_modal
            self.add_item(self._bar_length_select())
        elif self.category == "visibility":
            self.add_item(VisibilitySelect(self))
            self.add_item(BoolToggleButton(self, "buttons_visible", "Boutons sous /stats", row=2))
            self.add_item(BoolToggleButton(self, "allow_view_others", "Voir les stats d'un autre membre", row=2))
        elif self.category == "xp":
            self.add_item(discord.ui.Button(label="✏️ Modifier cooldown / bornes XP", style=discord.ButtonStyle.primary, row=1, custom_id="cfg:edit_xp"))
            self.children[-1].callback = self._open_xp_modal
            self.add_item(ExcludedRolesSelect(self))
            self.add_item(DisabledChannelsSelect(self))
            self.add_item(BoolToggleButton(self, "xp_disabled_on_commands", "XP désactivé sur les commandes", row=1))
        elif self.category == "voice":
            self.add_item(VoiceIgnoredChannelsSelect(self))
            self.add_item(BoolToggleButton(self, "voice_ignore_solo", "Ignorer si seul en vocal", row=1))

        preview_btn = discord.ui.Button(label="👁️ Prévisualiser", style=discord.ButtonStyle.secondary, row=4)
        preview_btn.callback = self._preview
        save_btn = discord.ui.Button(label="💾 Enregistrer", style=discord.ButtonStyle.success, row=4)
        save_btn.callback = self._save
        reset_btn = discord.ui.Button(label="🔄 Réinitialiser", style=discord.ButtonStyle.danger, row=4)
        reset_btn.callback = self._reset
        cancel_btn = discord.ui.Button(label="❌ Annuler", style=discord.ButtonStyle.secondary, row=4)
        cancel_btn.callback = self._cancel
        for b in (preview_btn, save_btn, reset_btn, cancel_btn):
            self.add_item(b)

    def _bar_length_select(self):
        options = [discord.SelectOption(label=f"{n} cases", value=str(n), default=self.pending.get("bar_length", 10) == n) for n in (5, 8, 10, 12, 15)]
        select = discord.ui.Select(placeholder="Longueur de la barre de progression", options=options, row=2)

        async def cb(interaction: discord.Interaction):
            self.pending["bar_length"] = int(select.values[0])
            await self.refresh(interaction)

        select.callback = cb
        return select

    async def _open_appearance_modal(self, interaction: discord.Interaction):
        await interaction.response.send_modal(StatsAppearanceModal(self))

    async def _open_xp_modal(self, interaction: discord.Interaction):
        await interaction.response.send_modal(StatsXPModal(self))

    def build_summary_embed(self) -> discord.Embed:
        p = self.pending
        e = discord.Embed(title="⚙️ Configuration de /stats et /level", color=p["color"])
        e.add_field(name="🎨 Apparence", value=f"Titre : {p['title_stats']}\nFooter : {p['footer']}\nCouleur : #{p['color']:06X}\nBarre : {p['emoji_filled']}{p['emoji_empty']} × {p['bar_length']}", inline=False)
        visible = ", ".join(label for key, label in VISIBILITY_OPTIONS if p.get(key, True)) or "Aucun"
        e.add_field(name="👁️ Champs visibles", value=visible, inline=False)
        e.add_field(name="✨ XP", value=f"Cooldown : {p['xp_cooldown']}s • Min/Max : {p['xp_min']}/{p['xp_max']}\nDésactivé sur commandes : {'Oui' if p.get('xp_disabled_on_commands') else 'Non'}\nRôles exclus : {len(p.get('xp_excluded_role_ids', []))}", inline=False)
        e.add_field(name="🔊 Vocal", value=f"Salons ignorés : {len(p.get('voice_ignored_channel_ids', []))}\nIgnorer si seul : {'Oui' if p.get('voice_ignore_solo') else 'Non'}", inline=False)
        e.add_field(name="🔘 Boutons sous /stats", value="Oui" if p.get("buttons_visible", True) else "Non", inline=True)
        e.add_field(name="🔒 Voir les stats des autres", value="Oui" if p.get("allow_view_others", True) else "Non", inline=True)
        e.set_footer(text="Rien n'est enregistré tant que vous n'avez pas cliqué sur 💾 Enregistrer.")
        return e

    async def refresh(self, interaction: discord.Interaction):
        embed = self.build_summary_embed()
        if not interaction.response.is_done():
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            try:
                await interaction.edit_original_response(embed=embed, view=self)
            except discord.HTTPException:
                pass

    async def _preview(self, interaction: discord.Interaction):
        member = interaction.user
        fake_settings = dict(self.pending)
        fake_settings.pop("_xp_channel_disabled", None)
        embed = await self.cog.build_stats_embed(self.guild, member, settings_override=fake_settings)
        await interaction.response.send_message(content="👁️ Aperçu (non enregistré) :", embed=embed, ephemeral=True)

    async def _save(self, interaction: discord.Interaction):
        to_save = dict(self.pending)
        disabled_channels = to_save.pop("_xp_channel_disabled", "")
        await self.cog.bot.db.set_guild_config(self.guild.id, "xp_channel_disabled", disabled_channels)
        await self.cog.bot.db.set_stats_settings(self.guild.id, to_save)
        embed = self.build_summary_embed()
        embed.set_footer(text="✅ Enregistré — ces réglages sont actifs immédiatement et resteront après un redémarrage.")
        await interaction.response.edit_message(embed=embed, view=self)

    async def _reset(self, interaction: discord.Interaction):
        await self.cog.bot.db.reset_stats_settings(self.guild.id)
        await self.cog.bot.db.set_guild_config(self.guild.id, "xp_channel_disabled", "")
        self.pending = dict(DEFAULT_STATS_SETTINGS)
        self.pending["_xp_channel_disabled"] = ""
        self.rebuild_items()
        embed = self.build_summary_embed()
        embed.set_footer(text="🔄 Réinitialisé aux valeurs par défaut et enregistré.")
        await interaction.response.edit_message(embed=embed, view=self)

    async def _cancel(self, interaction: discord.Interaction):
        for child in self.children:
            child.disabled = True
        embed = embeds.info("Configuration fermée — les modifications non enregistrées ont été abandonnées.")
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()


# =============================================================================
# Cog principal
# =============================================================================

class Levels(commands.Cog, name="Levels"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.cooldowns: dict[tuple, float] = {}

    async def cog_load(self):
        # Restaure le suivi du temps vocal après un redémarrage : on ne peut pas deviner
        # combien de temps s'est écoulé pendant que le bot était hors-ligne, donc on
        # referme proprement les anciennes sessions (sans ajouter ce temps "inconnu" à
        # voice_totals) puis on recrée une session fraîche pour tout membre actuellement
        # en vocal, pour que le suivi reprenne immédiatement plutôt que de rester cassé
        # jusqu'à ce que ce membre quitte et rejoigne le vocal.
        try:
            stale = await self.bot.db.get_all_voice_sessions()
            for row in stale:
                await self.bot.db.clear_voice_session(row["guild_id"], row["user_id"])
            for guild in self.bot.guilds:
                for channel in guild.voice_channels:
                    if guild.afk_channel and channel.id == guild.afk_channel.id:
                        continue
                    for member in channel.members:
                        if member.bot:
                            continue
                        await self.bot.db.start_voice_session(guild.id, member.id, channel.id)
        except Exception:
            import logging
            logging.getLogger("bot").exception("Impossible de restaurer les sessions vocales au démarrage")

    # -------------------------------------------------------------- XP

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        skip_ids = getattr(self.bot, "_xp_skip_ids", None)
        if skip_ids and message.id in skip_ids:
            return
        key = (message.guild.id, message.author.id)
        last = self.cooldowns.get(key, 0)
        settings = await self.bot.db.get_stats_settings(message.guild.id)
        cooldown = settings.get("xp_cooldown", XP_COOLDOWN_FALLBACK)
        if time.time() - last < cooldown:
            return

        if settings.get("xp_disabled_on_commands"):
            try:
                ctx = await self.bot.get_context(message)
                if ctx.valid:
                    return
            except Exception:
                pass

        conf = await self.bot.db.get_guild_config(message.guild.id)
        disabled_channels = set()
        if conf and conf["xp_channel_disabled"]:
            disabled_channels = {int(x) for x in conf["xp_channel_disabled"].split(",") if x.strip().isdigit()}
        if message.channel.id in disabled_channels:
            return

        excluded_roles = set(settings.get("xp_excluded_role_ids", []))
        if excluded_roles and isinstance(message.author, discord.Member):
            if any(r.id in excluded_roles for r in message.author.roles):
                return

        self.cooldowns[key] = time.time()
        asyncio.create_task(self._process_xp(message, settings, conf))

    async def _process_xp(self, message: discord.Message, settings: dict, conf):
        try:
            await self.bot.db.execute(
                "INSERT INTO message_counts (guild_id, user_id, count) VALUES (?, ?, 1) "
                "ON CONFLICT(guild_id, user_id) DO UPDATE SET count = count + 1",
                (message.guild.id, message.author.id),
            )
            xp_min = settings.get("xp_min", XP_MIN_FALLBACK)
            xp_max = settings.get("xp_max", XP_MAX_FALLBACK)
            if xp_min > xp_max:
                xp_min, xp_max = xp_max, xp_min
            multiplier = conf["xp_multiplier"] if conf and conf["xp_multiplier"] else 1.0
            gained = round(random.randint(xp_min, xp_max) * multiplier)
            row = await self.bot.db.get_level(message.guild.id, message.author.id)
            new_xp = row["xp"] + gained
            level = row["level"]
            needed = stats_service.xp_required_for_level(level)
            leveled_up = False
            while new_xp >= needed:
                new_xp -= needed
                level += 1
                needed = stats_service.xp_required_for_level(level)
                leveled_up = True
            await self.bot.db.execute(
                "UPDATE levels SET xp = ?, level = ? WHERE guild_id = ? AND user_id = ?",
                (new_xp, level, message.guild.id, message.author.id),
            )
            stats_service.invalidate_rank_cache(self.bot, message.guild.id, message.author.id)
            if leveled_up:
                channel = message.guild.get_channel(conf["level_channel"]) if conf and conf["level_channel"] else message.channel
                if channel:
                    try:
                        await channel.send(embed=embeds.success(f"🎉 {message.author.mention} passe au niveau **{level}** !"))
                    except discord.HTTPException:
                        pass
                role_row = await self.bot.db.fetchone(
                    "SELECT * FROM level_roles WHERE guild_id = ? AND level = ?", (message.guild.id, level)
                )
                if role_row:
                    role = message.guild.get_role(role_row["role_id"])
                    if role:
                        try:
                            await message.author.add_roles(role, reason=f"Niveau {level} atteint")
                        except discord.Forbidden:
                            pass
        except Exception:
            import logging
            logging.getLogger("bot").exception("Erreur lors du traitement XP en tâche de fond")

    # -------------------------------------------------------------- Permissions d'affichage

    async def _can_view(self, ctx: commands.Context, target: discord.Member, settings: dict) -> bool:
        if target.id == ctx.author.id:
            return True
        if isinstance(ctx.author, discord.Member) and ctx.author.guild_permissions.administrator:
            return True
        from config import OWNER_IDS
        if ctx.author.id in OWNER_IDS:
            return True
        if await self.bot.db.is_bot_manager(ctx.guild.id, ctx.author.id):
            return True
        return bool(settings.get("allow_view_others", True))

    # -------------------------------------------------------------- Embeds centralisés

    async def build_stats_embed(self, guild: discord.Guild, member: discord.Member, settings_override: dict | None = None) -> discord.Embed:
        settings = settings_override or await self.bot.db.get_stats_settings(guild.id)
        stats = await stats_service.get_member_statistics(self.bot, guild, member)
        e = discord.Embed(
            title=settings["title_stats"].format(display_name=member.display_name),
            description="Toutes les statistiques de ce membre sur le serveur.",
            color=settings["color"],
            timestamp=discord.utils.utcnow(),
        )
        e.set_thumbnail(url=member.display_avatar.url)
        e.add_field(name="📈 Niveau", value=f"Niveau {stats['level']}", inline=True)
        e.add_field(name="🏆 Classement", value=(f"#{stats['rank']}" if stats["is_ranked"] else "Non classé"), inline=True)
        if settings.get("show_messages", True):
            e.add_field(name="💬 Messages", value=str(stats["message_count"]), inline=True)
        bar_str, pct = stats_service.progress_bar(
            stats["xp_current"], stats["xp_needed"],
            length=settings.get("bar_length", 10),
            emoji_filled=settings.get("emoji_filled", "🟩"),
            emoji_empty=settings.get("emoji_empty", "⬜"),
        )
        e.add_field(name="✨ Progression", value=f"{bar_str}\n{stats['xp_current']}/{stats['xp_needed']} XP — {pct}%", inline=False)
        if settings.get("show_voice", True):
            e.add_field(name="🔊 Temps vocal", value=stats_service.format_duration(stats["voice_seconds"]), inline=True)
        if settings.get("show_economy", True):
            e.add_field(
                name="💰 Économie",
                value=f"Portefeuille : {stats['wallet']} 🪙\nBanque : {stats['bank']} 🏦\nTotal : {stats['total_money']} 🪙",
                inline=True,
            )
        if settings.get("show_reputation", True):
            e.add_field(name="⭐ Réputation", value=f"{stats['reputation']} point(s)", inline=True)
        if settings.get("show_join_date", True):
            e.add_field(
                name="📅 Membre depuis",
                value=f"<t:{int(stats['joined_at'].timestamp())}:D>" if stats["joined_at"] else "Inconnu",
                inline=True,
            )
        if settings.get("show_next_role", True):
            if stats["next_role"]:
                e.add_field(name="🎭 Prochain rôle", value=f"{stats['next_role'].mention} (niveau {stats['next_role_level']})", inline=True)
            else:
                e.add_field(name="🎭 Prochain rôle", value="Aucun palier configuré", inline=True)
        e.set_footer(text=settings.get("footer", DEFAULT_STATS_SETTINGS["footer"]))
        return e

    async def build_level_embed(self, guild: discord.Guild, member: discord.Member) -> discord.Embed:
        settings = await self.bot.db.get_stats_settings(guild.id)
        stats = await stats_service.get_member_statistics(self.bot, guild, member)
        remaining = max(0, stats["xp_needed"] - stats["xp_current"])
        e = discord.Embed(
            title=f"📈 Niveau de {member.display_name}",
            description=f"Encore **{remaining} XP** avant le prochain niveau.",
            color=settings["color"],
            timestamp=discord.utils.utcnow(),
        )
        e.set_thumbnail(url=member.display_avatar.url)
        e.add_field(name="Niveau actuel", value=str(stats["level"]), inline=True)
        e.add_field(name="Classement", value=(f"#{stats['rank']}" if stats["is_ranked"] else "Non classé"), inline=True)
        e.add_field(name="XP", value=f"{stats['xp_current']}/{stats['xp_needed']}", inline=True)
        bar_str, pct = stats_service.progress_bar(
            stats["xp_current"], stats["xp_needed"],
            length=settings.get("bar_length", 10),
            emoji_filled=settings.get("emoji_filled", "🟩"),
            emoji_empty=settings.get("emoji_empty", "⬜"),
        )
        e.add_field(name="Progression", value=f"{bar_str} — {pct}%", inline=False)
        if stats["next_role"]:
            e.add_field(name="Prochain palier", value=f"Niveau {stats['next_role_level']} → {stats['next_role'].mention}", inline=False)
        e.set_footer(text=settings.get("footer", DEFAULT_STATS_SETTINGS["footer"]))
        return e

    async def build_economy_embed(self, guild: discord.Guild, member: discord.Member) -> discord.Embed:
        settings = await self.bot.db.get_stats_settings(guild.id)
        stats = await stats_service.get_member_statistics(self.bot, guild, member)
        ranks = await stats_service.get_category_ranks(self.bot, guild.id, stats)
        bal_row = await self.bot.db.get_balance(guild.id, member.id)
        last_daily = bal_row["last_daily"] if bal_row else 0
        inv_rows = await self.bot.db.fetchall(
            "SELECT item_name, quantity FROM inventory WHERE guild_id = ? AND user_id = ? ORDER BY quantity DESC LIMIT 5",
            (guild.id, member.id),
        )
        e = discord.Embed(title=f"💰 Économie de {member.display_name}", color=settings["color"], timestamp=discord.utils.utcnow())
        e.set_thumbnail(url=member.display_avatar.url)
        e.add_field(name="Portefeuille", value=f"{stats['wallet']} 🪙", inline=True)
        e.add_field(name="Banque", value=f"{stats['bank']} 🏦", inline=True)
        e.add_field(name="Total", value=f"{stats['total_money']} 🪙", inline=True)
        e.add_field(name="Classement économique", value=f"#{ranks['economy_rank']}", inline=True)
        e.add_field(
            name="Dernière récompense quotidienne",
            value=f"<t:{last_daily}:R>" if last_daily else "Jamais réclamée",
            inline=True,
        )
        items_text = "\n".join(f"• {r['item_name']} × {r['quantity']}" for r in inv_rows) or "Inventaire vide."
        e.add_field(name="Objets principaux", value=items_text, inline=False)
        e.set_footer(text=settings.get("footer", DEFAULT_STATS_SETTINGS["footer"]))
        return e

    async def build_ranks_embed(self, guild: discord.Guild, member: discord.Member) -> discord.Embed:
        settings = await self.bot.db.get_stats_settings(guild.id)
        stats = await stats_service.get_member_statistics(self.bot, guild, member)
        ranks = await stats_service.get_category_ranks(self.bot, guild.id, stats)
        e = discord.Embed(title=f"🏆 Classement de {member.display_name}", color=settings["color"], timestamp=discord.utils.utcnow())
        e.set_thumbnail(url=member.display_avatar.url)
        e.add_field(name="XP / Niveau", value=(f"#{ranks['xp_rank']}" if stats["is_ranked"] else "Non classé"), inline=True)
        e.add_field(name="Messages", value=f"#{ranks['message_rank']}", inline=True)
        e.add_field(name="Temps vocal", value=f"#{ranks['voice_rank']}", inline=True)
        e.add_field(name="Économie", value=f"#{ranks['economy_rank']}", inline=True)
        e.add_field(name="Réputation", value=f"#{ranks['reputation_rank']}", inline=True)
        e.set_footer(text=settings.get("footer", DEFAULT_STATS_SETTINGS["footer"]))
        return e

    # -------------------------------------------------------------- Commandes

    async def _send_stats(self, ctx: commands.Context, membre: discord.Member = None):
        membre = membre or ctx.author
        settings = await self.bot.db.get_stats_settings(ctx.guild.id)
        try:
            if not await self._can_view(ctx, membre, settings):
                return await ctx.send(embed=embeds.error("La consultation des statistiques d'un autre membre est désactivée sur ce serveur."))
            embed = await self.build_stats_embed(ctx.guild, membre)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            return await ctx.send(embed=embeds.error("Impossible de récupérer les statistiques pour le moment (erreur Discord)."))
        except Exception:
            return await ctx.send(embed=embeds.error("Une erreur est survenue en préparant ces statistiques."))
        if settings.get("buttons_visible", True):
            view = StatsView(self, ctx.guild, membre, ctx.author.id)
            msg = await ctx.send(embed=embed, view=view)
            view.message = msg
        else:
            await ctx.send(embed=embed)

    @commands.hybrid_command(name="stats", description="Afficher le profil complet et les statistiques d'un membre.")
    @app_commands.describe(membre="Le membre visé (optionnel)")
    async def stats_cmd(self, ctx: commands.Context, membre: discord.Member = None):
        await self._send_stats(ctx, membre)

    @commands.hybrid_command(name="me", description="Afficher toutes vos statistiques personnelles sur ce serveur.", with_app_command=False)
    @app_commands.describe(membre="Le membre visé (optionnel)")
    async def me(self, ctx: commands.Context, membre: discord.Member = None):
        """Alias historique de /stats — conservé pour ne rien casser côté utilisateurs."""
        await self._send_stats(ctx, membre)

    async def _send_level(self, ctx: commands.Context, membre: discord.Member = None):
        membre = membre or ctx.author
        settings = await self.bot.db.get_stats_settings(ctx.guild.id)
        try:
            if not await self._can_view(ctx, membre, settings):
                return await ctx.send(embed=embeds.error("La consultation des statistiques d'un autre membre est désactivée sur ce serveur."))
            embed = await self.build_level_embed(ctx.guild, membre)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            return await ctx.send(embed=embeds.error("Impossible de récupérer le niveau pour le moment (erreur Discord)."))
        except Exception:
            return await ctx.send(embed=embeds.error("Une erreur est survenue en préparant ce niveau."))
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="level", description="Afficher votre niveau ou celui d'un membre.")
    @app_commands.describe(membre="Le membre visé (optionnel)")
    async def level_cmd(self, ctx: commands.Context, membre: discord.Member = None):
        await self._send_level(ctx, membre)

    @commands.hybrid_command(name="rank", description="Afficher votre niveau ou celui d'un membre.", with_app_command=False)
    @app_commands.describe(membre="Le membre visé (optionnel)")
    async def rank(self, ctx: commands.Context, membre: discord.Member = None):
        """Alias historique de /level — conservé pour ne rien casser côté utilisateurs."""
        await self._send_level(ctx, membre)

    @commands.hybrid_command(name="leaderboard-levels", description="Afficher le classement des niveaux.")
    async def leaderboard_levels(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall(
            "SELECT * FROM levels WHERE guild_id = ? ORDER BY level DESC, xp DESC LIMIT 15", (ctx.guild.id,)
        )
        if not rows:
            return await ctx.send(embed=embeds.info("Aucune donnée de niveau pour l'instant."))
        lines = []
        rank = 0
        for r in rows:
            member = ctx.guild.get_member(r["user_id"])
            if member is None or member.bot:
                continue
            rank += 1
            if rank > 10:
                break
            lines.append(f"**{rank}.** {member.display_name} — Niveau {r['level']} ({r['xp']} XP)")
        if not lines:
            return await ctx.send(embed=embeds.info("Aucune donnée de niveau pour l'instant."))
        await ctx.send(embed=embeds.neutral("🏆 Classement des niveaux", "\n".join(lines)))

    @commands.hybrid_command(name="set-level-role", description="[Admin] Associer un rôle à un niveau.", with_app_command=False)
    @app_commands.describe(niveau="Le niveau requis", role="Le rôle à attribuer")
    @checks.is_owner_or_admin_for("configuration")
    async def set_level_role(self, ctx: commands.Context, niveau: int, role: discord.Role):
        await self.bot.db.execute(
            "INSERT INTO level_roles (guild_id, level, role_id) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, level) DO UPDATE SET role_id = excluded.role_id",
            (ctx.guild.id, niveau, role.id),
        )
        await ctx.send(embed=embeds.success(f"Le rôle {role.mention} sera attribué au niveau **{niveau}**."))

    @commands.hybrid_command(name="remove-level-role", description="[Admin] Retirer l'association d'un rôle de niveau.", with_app_command=False)
    @app_commands.describe(niveau="Le niveau concerné")
    @checks.is_owner_or_admin_for("configuration")
    async def remove_level_role(self, ctx: commands.Context, niveau: int):
        await self.bot.db.execute("DELETE FROM level_roles WHERE guild_id = ? AND level = ?", (ctx.guild.id, niveau))
        await ctx.send(embed=embeds.success(f"Association de rôle retirée pour le niveau **{niveau}**."))

    @commands.hybrid_command(name="level-roles", description="Lister les rôles de niveau configurés.", with_app_command=False)
    async def level_roles(self, ctx: commands.Context):
        rows = await self.bot.db.fetchall("SELECT * FROM level_roles WHERE guild_id = ? ORDER BY level ASC", (ctx.guild.id,))
        if not rows:
            return await ctx.send(embed=embeds.info("Aucun rôle de niveau configuré."))
        lines = []
        for r in rows:
            role = ctx.guild.get_role(r["role_id"])
            lines.append(f"Niveau **{r['level']}** → {role.mention if role else 'Rôle supprimé'}")
        await ctx.send(embed=embeds.neutral("🎖️ Rôles de niveau", "\n".join(lines)))

    @commands.hybrid_command(name="set-xp", description="[Admin] Définir l'XP d'un membre.", with_app_command=False)
    @app_commands.describe(membre="Le membre visé", xp="La valeur d'XP")
    @checks.is_owner_or_admin_for("configuration")
    async def set_xp(self, ctx: commands.Context, membre: discord.Member, xp: int):
        if membre.bot:
            return await ctx.send(embed=embeds.error("Un bot ne peut pas avoir d'XP."))
        await self.bot.db.ensure_level(ctx.guild.id, membre.id)
        await self.bot.db.execute("UPDATE levels SET xp = ? WHERE guild_id = ? AND user_id = ?", (max(0, xp), ctx.guild.id, membre.id))
        stats_service.invalidate_rank_cache(self.bot, ctx.guild.id, membre.id)
        await ctx.send(embed=embeds.success(f"XP de {membre.mention} défini à **{max(0, xp)}**."))

    @commands.hybrid_command(name="add-xp", description="[Admin] Ajouter de l'XP à un membre.", with_app_command=False)
    @app_commands.describe(membre="Le membre visé", xp="La quantité d'XP à ajouter")
    @checks.is_owner_or_admin_for("configuration")
    async def add_xp(self, ctx: commands.Context, membre: discord.Member, xp: int):
        if membre.bot:
            return await ctx.send(embed=embeds.error("Un bot ne peut pas avoir d'XP."))
        await self.bot.db.ensure_level(ctx.guild.id, membre.id)
        await self.bot.db.execute("UPDATE levels SET xp = xp + ? WHERE guild_id = ? AND user_id = ?", (xp, ctx.guild.id, membre.id))
        stats_service.invalidate_rank_cache(self.bot, ctx.guild.id, membre.id)
        await ctx.send(embed=embeds.success(f"**{xp} XP** ajoutés à {membre.mention}."))

    @commands.hybrid_command(name="reset-levels", description="[Admin] Réinitialiser tous les niveaux du serveur.", with_app_command=False)
    @checks.is_owner_or_admin_for("configuration")
    async def reset_levels(self, ctx: commands.Context):
        await self.bot.db.execute("DELETE FROM levels WHERE guild_id = ?", (ctx.guild.id,))
        stats_service.invalidate_rank_cache(self.bot, ctx.guild.id)
        await ctx.send(embed=embeds.success("Tous les niveaux du serveur ont été réinitialisés."))

    @commands.hybrid_command(name="profile", description="Afficher votre profil communautaire.")
    @app_commands.describe(membre="Le membre visé (optionnel)")
    async def profile(self, ctx: commands.Context, membre: discord.Member = None):
        membre = membre or ctx.author
        bio_row = await self.bot.db.fetchone(
            "SELECT * FROM profiles WHERE guild_id = ? AND user_id = ?", (ctx.guild.id, membre.id)
        )
        try:
            stats = await stats_service.get_member_statistics(self.bot, ctx.guild, membre)
        except Exception:
            return await ctx.send(embed=embeds.error("Une erreur est survenue en préparant ce profil."))
        e = embeds.neutral(f"🪪 Profil de {membre.display_name}")
        e.set_thumbnail(url=membre.display_avatar.url)
        e.add_field(name="Niveau", value=stats["level"], inline=True)
        e.add_field(name="Messages", value=stats["message_count"], inline=True)
        e.add_field(name="Bio", value=(bio_row["bio"] if bio_row and bio_row["bio"] else "Aucune bio définie."), inline=False)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="set-bio", description="Définir votre biographie de profil.", with_app_command=False)
    @app_commands.describe(texte="Votre biographie (200 caractères max)")
    async def set_bio(self, ctx: commands.Context, *, texte: str):
        texte = texte[:200]
        await self.bot.db.execute(
            "INSERT INTO profiles (guild_id, user_id, bio) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, user_id) DO UPDATE SET bio = excluded.bio",
            (ctx.guild.id, ctx.author.id, texte),
        )
        await ctx.send(embed=embeds.success("Votre bio a été mise à jour."))

    @commands.hybrid_command(name="voice-time", description="Afficher le temps passé en vocal par un membre.", with_app_command=False)
    @app_commands.describe(membre="Le membre visé (optionnel)")
    async def voice_time(self, ctx: commands.Context, membre: discord.Member = None):
        membre = membre or ctx.author
        try:
            stats = await stats_service.get_member_statistics(self.bot, ctx.guild, membre)
        except Exception:
            return await ctx.send(embed=embeds.error("Impossible de récupérer le temps vocal pour le moment."))
        await ctx.send(embed=embeds.info(f"🔊 {membre.display_name} a passé **{stats_service.format_duration(stats['voice_seconds'])}** en vocal."))

    @commands.hybrid_command(name="statsconfig", description="[Admin] Configurer l'apparence et le comportement de /stats et /level.", with_app_command=False)
    @checks.is_owner_or_admin_for("configuration")
    async def statsconfig(self, ctx: commands.Context):
        settings = await self.bot.db.get_stats_settings(ctx.guild.id)
        conf = await self.bot.db.get_guild_config(ctx.guild.id)
        view = StatsConfigView(self, ctx.guild, ctx.author.id, settings)
        if conf and conf["xp_channel_disabled"]:
            view.pending["_xp_channel_disabled"] = conf["xp_channel_disabled"]
        embed = view.build_summary_embed()
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg

    # -------------------------------------------------------------- Temps vocal

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return
        guild = member.guild
        settings = await self.bot.db.get_stats_settings(guild.id)
        ignored_channels = set(settings.get("voice_ignored_channel_ids", []))
        ignore_solo = settings.get("voice_ignore_solo", False)

        def trackable(channel: discord.abc.Connectable | None) -> bool:
            if channel is None:
                return False
            if guild.afk_channel and channel.id == guild.afk_channel.id:
                return False
            if channel.id in ignored_channels:
                return False
            if ignore_solo and len([m for m in getattr(channel, "members", []) if not m.bot]) <= 1:
                return False
            return True

        # Quitte un salon suivi (départ du vocal, ou passage vers un salon non suivi)
        if before.channel is not None and (after.channel is None or before.channel.id != after.channel.id):
            if trackable(before.channel):
                await self.bot.db.end_voice_session(guild.id, member.id)

        # Rejoint un salon suivi (arrivée en vocal, ou changement vers un salon suivi)
        if after.channel is not None and (before.channel is None or before.channel.id != after.channel.id):
            if trackable(after.channel):
                await self.bot.db.start_voice_session(guild.id, member.id, after.channel.id)


async def setup(bot: commands.Bot):
    await bot.add_cog(Levels(bot))
