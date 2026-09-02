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

from utils import embeds, checks, stats_service, design_system, visual_v5
from utils import sentrix_panels as panels
from database.db import now, DEFAULT_STATS_SETTINGS

XP_COOLDOWN_FALLBACK = 60
XP_MIN_FALLBACK, XP_MAX_FALLBACK = 10, 25

# Ré-exporté pour compatibilité (certaines parties du bot pourraient encore importer ce
# nom depuis cogs.levels) — pointe directement vers la fonction centrale.
xp_for_level = stats_service.xp_required_for_level


# =============================================================================
# Boutons de navigation sous /stats
# =============================================================================


def _reponse(titre: str, description: str, *, kind: str = "brand") -> discord.Embed:
    """Reponse au format canonique SentriX.

    Ce module repondait en texte nu : ni couleur d'intention, ni pied de page,
    ni barre d'identite, alors que le reste du bot en porte.
    """
    return embeds._base(titre, description, kind=kind)


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
        await interaction.response.send_message(embed=_reponse("Niveaux", "○ Ce menu n'est pas pour vous — utilisez `/stats` de votre côté pour consulter vos propres statistiques.", kind="danger"), ephemeral=True)
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
        for item in (self.titre, self.footer, self.couleur):
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
        self.label = f"{self.base_label} : {'● Oui' if value else '○ Non'}"

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


class LevelAnnounceChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, view: "StatsConfigView"):
        self.view_ref = view
        current_id = view.pending.get("_level_channel")
        current = [c] if current_id and (c := view.guild.get_channel(current_id)) else []
        super().__init__(
            placeholder="Salon d'annonce des montées de niveau (vide = salon du message)",
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            min_values=0, max_values=1, row=2, default_values=current,
        )

    async def callback(self, interaction: discord.Interaction):
        self.view_ref.pending["_level_channel"] = self.values[0].id if self.values else None
        await self.view_ref.refresh(interaction)


class StatsEconomyModal(discord.ui.Modal, title="Économie et réputation"):
    def __init__(self, view: "StatsConfigView"):
        super().__init__()
        self.view_ref = view
        self.emoji = discord.ui.TextInput(label="Emoji de l'économie (ex: 🪙, 💵, 🥇)", default=view.pending.get("economy_emoji", "🪙"), max_length=10)
        self.rep_cooldown = discord.ui.TextInput(
            label="Cooldown de réputation (en heures)",
            default=str(view.pending.get("reputation_cooldown", 86400) // 3600),
            max_length=4,
        )
        self.add_item(self.emoji)
        self.add_item(self.rep_cooldown)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            hours = int(str(self.rep_cooldown.value).strip())
            if hours <= 0:
                raise ValueError
        except ValueError:
            return await interaction.response.send_message(embed=embeds.error("Le cooldown doit être un nombre d'heures positif."), ephemeral=True)
        self.view_ref.pending["economy_emoji"] = str(self.emoji.value).strip() or "🪙"
        self.view_ref.pending["reputation_cooldown"] = hours * 3600
        await self.view_ref.refresh(interaction)


class LevelRoleLevelModal(discord.ui.Modal, title="Quel niveau ?"):
    def __init__(self, cog: "Levels", guild: discord.Guild):
        super().__init__()
        self.cog = cog
        self.guild = guild
        self.niveau = discord.ui.TextInput(label="Numéro du niveau", placeholder="ex: 5", max_length=6)
        self.add_item(self.niveau)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            level = int(str(self.niveau.value).strip())
        except ValueError:
            return await interaction.response.send_message(embed=embeds.error("Le niveau doit être un nombre entier."), ephemeral=True)
        if level < 0:
            return await interaction.response.send_message(embed=embeds.error("Le niveau ne peut pas être négatif."), ephemeral=True)
        view = LevelRoleSelectView(self.cog, self.guild, level)
        await interaction.response.send_message(
            content=f"Quel rôle attribuer au niveau **{level}** ?", view=view, ephemeral=True
        )


class LevelRoleSelectView(discord.ui.View):
    def __init__(self, cog: "Levels", guild: discord.Guild, level: int):
        super().__init__(timeout=60)
        self.cog = cog
        self.guild = guild
        self.level = level

    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="Choisir le rôle", min_values=1, max_values=1)
    async def pick(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        role = select.values[0]
        if role.id == self.guild.default_role.id:
            return await interaction.response.edit_message(content="○ Impossible d'utiliser @everyone comme rôle de niveau.", view=None)
        warn = ""
        if role >= self.guild.me.top_role:
            warn = (
                f"\n⚠️ Ce rôle est actuellement plus haut que le mien dans la hiérarchie — "
                f"je ne pourrai pas l'attribuer tant qu'il ne sera pas plus bas. Le palier est quand même enregistré."
            )
        await self.cog.bot.db.execute(
            "INSERT INTO level_roles (guild_id, level, role_id) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, level) DO UPDATE SET role_id = excluded.role_id",
            (self.guild.id, self.level, role.id),
        )
        await interaction.response.edit_message(content=f"● Niveau **{self.level}** → {role.mention} enregistré.{warn}", view=None)


class LevelRoleTargetSelectView(discord.ui.View):
    """Étape 1 des flux "Modifier"/"Supprimer" : choisir SUR QUEL palier agir."""

    def __init__(self, cog: "Levels", guild: discord.Guild, rows, mode: str):
        super().__init__(timeout=60)
        self.cog = cog
        self.guild = guild
        self.mode = mode  # "edit" ou "delete"
        options = []
        for r in rows[:25]:
            role = guild.get_role(r["role_id"])
            label = f"Niveau {r['level']} → {role.name if role else 'rôle supprimé'}"
            options.append(discord.SelectOption(label=label[:100], value=str(r["level"])))
        self.select = discord.ui.Select(placeholder="Choisir un palier", options=options)
        self.select.callback = self._chosen
        self.add_item(self.select)

    async def _chosen(self, interaction: discord.Interaction):
        level = int(self.select.values[0])
        if self.mode == "edit":
            view = LevelRoleSelectView(self.cog, self.guild, level)
            await interaction.response.edit_message(content=f"Quel nouveau rôle pour le niveau **{level}** ?", view=view)
        else:
            await self.cog.bot.db.execute(
                "DELETE FROM level_roles WHERE guild_id = ? AND level = ?", (self.guild.id, level)
            )
            await interaction.response.edit_message(content=f"🗑️ Palier de niveau **{level}** supprimé.", view=None)


class StatsConfigCategorySelect(discord.ui.Select):
    def __init__(self, view: "StatsConfigView"):
        self.view_ref = view
        options = [
            discord.SelectOption(label="🎨 Apparence (couleur, titre, footer, emojis)", value="appearance"),
            discord.SelectOption(label="👁️ Visibilité des champs", value="visibility"),
            discord.SelectOption(label="✨ XP (cooldown, bornes, exclusions)", value="xp"),
            discord.SelectOption(label="🔊 Vocal (salons ignorés)", value="voice"),
            discord.SelectOption(label="🎭 Niveaux (paliers, annonce)", value="levels"),
            discord.SelectOption(label="💰 Économie & Réputation (emoji, cooldown)", value="economy"),
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
        await interaction.response.send_message(embed=_reponse("Niveaux", "○ Seule la personne ayant ouvert ce panneau peut l'utiliser.", kind="danger"), ephemeral=True)
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
        elif self.category == "levels":
            add_btn = discord.ui.Button(label="➕ Ajouter un palier", style=discord.ButtonStyle.success, row=1)
            add_btn.callback = self._level_role_add
            edit_btn = discord.ui.Button(label="✏️ Modifier", style=discord.ButtonStyle.primary, row=1)
            edit_btn.callback = self._level_role_edit
            del_btn = discord.ui.Button(label="🗑️ Supprimer", style=discord.ButtonStyle.danger, row=1)
            del_btn.callback = self._level_role_delete
            list_btn = discord.ui.Button(label="📋 Liste des paliers", style=discord.ButtonStyle.secondary, row=1)
            list_btn.callback = self._level_role_list
            for b in (add_btn, edit_btn, del_btn, list_btn):
                self.add_item(b)
            self.add_item(LevelAnnounceChannelSelect(self))
            self.add_item(BoolToggleButton(self, "level_keep_old_roles", "Garder les anciens rôles", row=3))
            self.add_item(BoolToggleButton(self, "level_announce_enabled", "Annonce de niveau activée", row=3))
        elif self.category == "economy":
            emoji_btn = discord.ui.Button(label="✏️ Modifier emoji / cooldown réputation", style=discord.ButtonStyle.primary, row=1)
            emoji_btn.callback = self._open_economy_modal
            self.add_item(emoji_btn)

        preview_btn = discord.ui.Button(label="👁️ Prévisualiser", style=discord.ButtonStyle.secondary, row=4)
        preview_btn.callback = self._preview
        save_btn = discord.ui.Button(label="💾 Enregistrer", style=discord.ButtonStyle.success, row=4)
        save_btn.callback = self._save
        reset_btn = discord.ui.Button(label="🔄 Réinitialiser", style=discord.ButtonStyle.danger, row=4)
        reset_btn.callback = self._reset
        cancel_btn = discord.ui.Button(label="○ Annuler", style=discord.ButtonStyle.secondary, row=4)
        cancel_btn.callback = self._cancel
        for b in (preview_btn, save_btn, reset_btn, cancel_btn):
            self.add_item(b)

    async def _open_appearance_modal(self, interaction: discord.Interaction):
        await interaction.response.send_modal(StatsAppearanceModal(self))

    async def _open_xp_modal(self, interaction: discord.Interaction):
        await interaction.response.send_modal(StatsXPModal(self))

    async def _open_economy_modal(self, interaction: discord.Interaction):
        await interaction.response.send_modal(StatsEconomyModal(self))

    async def _level_role_add(self, interaction: discord.Interaction):
        await interaction.response.send_modal(LevelRoleLevelModal(self.cog, self.guild))

    async def _level_role_edit(self, interaction: discord.Interaction):
        rows = await self.cog.bot.db.fetchall("SELECT * FROM level_roles WHERE guild_id = ? ORDER BY level ASC", (self.guild.id,))
        if not rows:
            return await interaction.response.send_message(embed=embeds.info("Aucun palier configuré à modifier."), ephemeral=True)
        view = LevelRoleTargetSelectView(self.cog, self.guild, rows, "edit")
        await interaction.response.send_message(content="Quel palier modifier ?", view=view, ephemeral=True)

    async def _level_role_delete(self, interaction: discord.Interaction):
        rows = await self.cog.bot.db.fetchall("SELECT * FROM level_roles WHERE guild_id = ? ORDER BY level ASC", (self.guild.id,))
        if not rows:
            return await interaction.response.send_message(embed=embeds.info("Aucun palier configuré à supprimer."), ephemeral=True)
        view = LevelRoleTargetSelectView(self.cog, self.guild, rows, "delete")
        await interaction.response.send_message(content="Quel palier supprimer ?", view=view, ephemeral=True)

    async def _level_role_list(self, interaction: discord.Interaction):
        rows = await self.cog.bot.db.fetchall("SELECT * FROM level_roles WHERE guild_id = ? ORDER BY level ASC", (self.guild.id,))
        if not rows:
            return await interaction.response.send_message(embed=embeds.info("Aucun palier configuré."), ephemeral=True)
        lines = []
        for r in rows:
            role = self.guild.get_role(r["role_id"])
            lines.append(f"Niveau **{r['level']}** → {role.mention if role else '⚠️ rôle supprimé'}")
        await interaction.response.send_message(embed=embeds.neutral("🎭 Paliers de niveau configurés", "\n".join(lines)), ephemeral=True)

    def build_summary_embed(self) -> discord.Embed:
        p = self.pending
        # La couleur est celle configuree par le serveur : on la conserve et on passe
        # par le constructeur canonique pour le pied de page et la barre d'identite.
        e = embeds._base("⚙️ Configuration de /stats et /level", None, colour=int(p["color"]))
        e.add_field(name="🎨 Apparence", value=f"Titre : {p['title_stats']}\nFooter : {p['footer']}\nCouleur : #{p['color']:06X}", inline=False)
        visible = ", ".join(label for key, label in VISIBILITY_OPTIONS if p.get(key, True)) or "Aucun"
        e.add_field(name="👁️ Champs visibles", value=visible, inline=False)
        e.add_field(name="✨ XP", value=f"Cooldown : {p['xp_cooldown']}s • Min/Max : {p['xp_min']}/{p['xp_max']}\nDésactivé sur commandes : {'Oui' if p.get('xp_disabled_on_commands') else 'Non'}\nRôles exclus : {len(p.get('xp_excluded_role_ids', []))}", inline=False)
        e.add_field(name="🔊 Vocal", value=f"Salons ignorés : {len(p.get('voice_ignored_channel_ids', []))}\nIgnorer si seul : {'Oui' if p.get('voice_ignore_solo') else 'Non'}", inline=False)
        level_channel_id = p.get("_level_channel")
        level_channel_text = f"<#{level_channel_id}>" if level_channel_id else "Salon du message (par défaut)"
        e.add_field(
            name="🎭 Niveaux",
            value=f"Annonce : {'Activée' if p.get('level_announce_enabled', True) else 'Désactivée'}\nSalon d'annonce : {level_channel_text}\nGarder les anciens rôles : {'Oui' if p.get('level_keep_old_roles') else 'Non'}",
            inline=False,
        )
        e.add_field(name="💰 Emoji économie", value=p.get("economy_emoji", "🪙"), inline=True)
        e.add_field(name="⭐ Cooldown réputation", value=stats_service.format_duration(p.get("reputation_cooldown", 86400)), inline=True)
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
        level_channel = to_save.pop("_level_channel", None)
        await self.cog.bot.db.set_guild_config(self.guild.id, "xp_channel_disabled", disabled_channels)
        await self.cog.bot.db.set_guild_config(self.guild.id, "level_channel", level_channel)
        await self.cog.bot.db.set_stats_settings(self.guild.id, to_save)
        embed = self.build_summary_embed()
        embed.set_footer(text="● Enregistré — ces réglages sont actifs immédiatement et resteront après un redémarrage.")
        await interaction.response.edit_message(embed=embed, view=self)

    async def _reset(self, interaction: discord.Interaction):
        await self.cog.bot.db.reset_stats_settings(self.guild.id)
        await self.cog.bot.db.set_guild_config(self.guild.id, "xp_channel_disabled", "")
        self.pending = dict(DEFAULT_STATS_SETTINGS)
        self.pending["_xp_channel_disabled"] = ""
        self.pending["_level_channel"] = None
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

class _LevelRepairConfirmView(discord.ui.View):
    """Confirmation obligatoire avant +levelrepair — n'agit que sur le clic de l'auteur
    de la commande, se désactive après usage ou expiration (5 min)."""

    def __init__(self, *, author_id: int, timeout: float = 300):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.confirmed = False
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(embed=embeds.error("Seul l'auteur de la commande peut confirmer."), ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass

    @discord.ui.button(label="Confirmer la réparation", style=discord.ButtonStyle.danger, emoji="🛠️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = False
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=embeds.info("Réparation annulée — aucune donnée modifiée."), view=self)
        self.stop()


class Levels(commands.Cog, name="Levels"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.cooldowns: dict[tuple, float] = {}
        # Verrou lecture-modification-écriture par (guild_id, user_id) : deux messages
        # quasi simultanés du même membre déclenchaient deux tâches _process_xp en
        # parallèle, chacune lisant la même valeur de départ puis réécrivant — la
        # dernière écriture "gagnait" et l'autre gain d'XP était perdu. Un dict de
        # verrous (créés à la demande, jamais purgés — coût mémoire négligeable) rend
        # ce chemin strictement séquentiel par membre, comme pour l'économie
        # (Database._economy_lock) et les sanctions (Database._sanctions_lock).
        self._xp_locks: dict[tuple, asyncio.Lock] = {}

    def _get_xp_lock(self, guild_id: int, user_id: int) -> asyncio.Lock:
        key = (guild_id, user_id)
        lock = self._xp_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._xp_locks[key] = lock
        return lock

    async def _apply_xp_delta(self, guild_id: int, user_id: int, delta: int) -> tuple[int, int, bool]:
        """Ajoute (ou retire) `delta` XP à un membre, sous verrou, en recalculant TOUJOURS
        le niveau correctement (jamais de xp qui dépasse le seuil du niveau courant sans
        faire monter le niveau — c'était le cas de +add-xp avant cette correction).
        Retourne (nouveau_xp, nouveau_niveau, a_gagné_un_niveau)."""
        await self.bot.db.ensure_level(guild_id, user_id)
        lock = self._get_xp_lock(guild_id, user_id)
        async with lock:
            row = await self.bot.db.get_level(guild_id, user_id)
            new_xp = max(0, row["xp"] + delta)
            level = row["level"]
            needed = stats_service.xp_required_for_level(level)
            leveled_up = False
            while new_xp >= needed:
                new_xp -= needed
                level += 1
                needed = stats_service.xp_required_for_level(level)
                leveled_up = True
            # En cas de retrait d'XP (delta négatif), on ne fait jamais descendre le
            # niveau automatiquement — un admin qui veut baisser un niveau doit utiliser
            # +set-xp explicitement avec la valeur souhaitée, jamais un effet de bord.
            await self.bot.db.execute(
                "UPDATE levels SET xp = ?, level = ?, updated_at = ? WHERE guild_id = ? AND user_id = ?",
                (new_xp, level, now(), guild_id, user_id),
            )
        stats_service.invalidate_rank_cache(self.bot, guild_id, user_id)
        return new_xp, level, leveled_up

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

            # _apply_xp_delta gère le verrou par membre (lecture+calcul+écriture atomiques)
            # et le recalcul du niveau — source unique partagée avec +add-xp.
            new_xp, level, leveled_up = await self._apply_xp_delta(message.guild.id, message.author.id, gained)
            if leveled_up:
                if settings.get("level_announce_enabled", True):
                    channel = message.guild.get_channel(conf["level_channel"]) if conf and conf["level_channel"] else message.channel
                    if channel:
                        allowed_mentions = discord.AllowedMentions(
                            users=[message.author],
                            roles=False,
                            everyone=False,
                            replied_user=False,
                        )
                        try:
                            card_stats = await stats_service.get_member_statistics(
                                self.bot, message.guild, message.author
                            )
                            design_settings = await self.bot.db.get_design_settings(message.guild.id)
                            buffer = await visual_v5.render_member_card(
                                message.author,
                                message.guild,
                                card_stats,
                                design_settings,
                                level_up=level,
                            )
                            file = discord.File(buffer, filename="sentrix-level-up.png")
                            level_embed = discord.Embed(
                                title="Niveau atteint",
                                description=f"**{message.author.display_name}** passe au niveau **{level}**.",
                                colour=discord.Colour(design_settings.get("primary_color", 0x6C5CE7)),
                            )
                            level_embed.set_image(url="attachment://sentrix-level-up.png")
                            await channel.send(
                                content=message.author.mention,
                                embed=level_embed,
                                file=file,
                                allowed_mentions=allowed_mentions,
                            )
                        except Exception:
                            try:
                                await channel.send(
                                    content=message.author.mention,
                                    embed=embeds.success(
                                        f"**{message.author.display_name}** passe au niveau **{level}** !"
                                    ),
                                    allowed_mentions=allowed_mentions,
                                )
                            except discord.HTTPException:
                                pass
                await self._assign_level_role(message.guild, message.author, level, settings)
        except Exception:
            import logging
            logging.getLogger("bot").exception("Erreur lors du traitement XP en tâche de fond")

    async def _assign_level_role(self, guild: discord.Guild, member: discord.Member, level: int, settings: dict):
        """Attribue le rôle du palier atteint (uniquement au moment de la montée de
        niveau — jamais juste parce que /stats est consulté, voir demande explicite).
        Vérifie la permission "Gérer les rôles", la hiérarchie du rôle du bot, exclut
        @everyone, gère un rôle supprimé, et journalise le résultat."""
        logger = __import__("logging").getLogger("bot")
        role_row = await self.bot.db.fetchone(
            "SELECT * FROM level_roles WHERE guild_id = ? AND level = ?", (guild.id, level)
        )
        if not role_row:
            return
        role = guild.get_role(role_row["role_id"])
        if role is None:
            logger.info("Rôle de niveau %s introuvable (supprimé) sur %s (%s).", level, guild.name, guild.id)
            return
        if role.id == guild.default_role.id:
            logger.warning("Rôle de niveau %s pointe vers @everyone sur %s — ignoré par sécurité.", level, guild.id)
            return
        if not guild.me.guild_permissions.manage_roles:
            logger.warning("Impossible d'attribuer le rôle de niveau %s sur %s : permission Gérer les rôles manquante.", level, guild.id)
            return
        if role >= guild.me.top_role:
            logger.warning(
                "Impossible d'attribuer le rôle de niveau %s (%s) sur %s : il est au-dessus du rôle du bot dans la hiérarchie.",
                level, role.name, guild.id,
            )
            return
        try:
            to_add = [role]
            to_remove = []
            if not settings.get("level_keep_old_roles", False):
                # Retire les anciens rôles de niveau (paliers inférieurs) pour ne garder
                # que le plus récent — seulement si l'option "garder les anciens rôles"
                # est désactivée (comportement par défaut).
                other_rows = await self.bot.db.fetchall(
                    "SELECT role_id FROM level_roles WHERE guild_id = ? AND level < ?", (guild.id, level)
                )
                for r in other_rows:
                    old_role = guild.get_role(r["role_id"])
                    if old_role and old_role in member.roles and old_role.id != guild.default_role.id:
                        to_remove.append(old_role)
            await member.add_roles(*to_add, reason=f"Niveau {level} atteint")
            if to_remove:
                await member.remove_roles(*to_remove, reason=f"Anciens paliers retirés (niveau {level} atteint)")
            logger.info("Rôle de niveau %s (%s) attribué à %s sur %s.", level, role.name, member.id, guild.id)
        except discord.Forbidden:
            logger.warning("Permission refusée en attribuant le rôle de niveau %s à %s sur %s.", level, member.id, guild.id)
        except discord.HTTPException:
            logger.warning("Erreur Discord en attribuant le rôle de niveau %s à %s sur %s.", level, member.id, guild.id)

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

    @staticmethod
    def _next_role_text(stats: dict) -> str:
        """Texte du champ "🎭 Prochain rôle", identique partout (section 3 de la demande)."""
        if stats["next_level_role"]:
            return f"Niveau {stats['next_level_requirement']} → {stats['next_level_role'].mention}\nEncore {stats['remaining_levels']} niveau(x)."
        if stats["all_roles_obtained"]:
            return "Tous les paliers ont été atteints ●"
        return "Aucun palier configuré"

    async def build_stats_embed(self, guild: discord.Guild, member: discord.Member, settings_override: dict | None = None) -> discord.Embed:
        settings = settings_override or await self.bot.db.get_stats_settings(guild.id)
        stats = await stats_service.get_member_statistics(self.bot, guild, member)
        eco_emoji = settings.get("economy_emoji", "🪙")
        e = discord.Embed(
            title=settings["title_stats"].format(display_name=member.display_name),
            description="Toutes les statistiques de ce membre sur le serveur.",
            color=settings["color"],
            timestamp=discord.utils.utcnow(),
        )
        e.set_thumbnail(url=member.display_avatar.url)
        e.add_field(name="📈 Niveau", value=f"Niveau {stats['current_level']}", inline=True)
        e.add_field(name="🏆 Classement", value=(f"#{stats['rank']}" if stats["is_ranked"] else "Non classé"), inline=True)
        if settings.get("show_messages", True):
            e.add_field(name="💬 Messages", value=stats_service.format_number(stats["message_count"]), inline=True)
        e.add_field(
            name="✨ Progression",
            value=f"{stats_service.format_number(stats['current_level_xp'])}/{stats_service.format_number(stats['required_xp'])} XP — {stats['progress_pct']}%",
            inline=False,
        )
        if settings.get("show_voice", True):
            e.add_field(name="🔊 Temps vocal", value=stats_service.format_duration(stats["voice_time"]), inline=True)
        if settings.get("show_economy", True):
            e.add_field(
                name="💰 Économie",
                value=(
                    f"Portefeuille : {stats_service.format_number(stats['wallet'])} {eco_emoji}\n"
                    f"Banque : {stats_service.format_number(stats['bank'])} 🏦\n"
                    f"Total : {stats_service.format_number(stats['total_money'])} {eco_emoji}"
                ),
                inline=True,
            )
        if settings.get("show_reputation", True):
            e.add_field(name="⭐ Réputation", value=f"{stats_service.format_number(stats['reputation'])} point(s)", inline=True)
        if settings.get("show_join_date", True):
            e.add_field(
                name="📅 Membre depuis",
                value=f"<t:{int(stats['joined_at'].timestamp())}:D>" if stats["joined_at"] else "Inconnu",
                inline=True,
            )
        if settings.get("show_next_role", True):
            e.add_field(name="🎭 Prochain rôle", value=self._next_role_text(stats), inline=False)
        e.set_footer(text=settings.get("footer", DEFAULT_STATS_SETTINGS["footer"]))
        return e

    async def build_level_embed(self, guild: discord.Guild, member: discord.Member) -> discord.Embed:
        settings = await self.bot.db.get_stats_settings(guild.id)
        stats = await stats_service.get_member_statistics(self.bot, guild, member)
        remaining_xp = max(0, stats["required_xp"] - stats["current_level_xp"])
        e = discord.Embed(
            title=f"📈 Niveau de {member.display_name}",
            description=f"Encore **{stats_service.format_number(remaining_xp)} XP** avant le prochain niveau.",
            color=settings["color"],
            timestamp=discord.utils.utcnow(),
        )
        e.set_thumbnail(url=member.display_avatar.url)
        e.add_field(name="Niveau actuel", value=str(stats["current_level"]), inline=True)
        e.add_field(name="Classement", value=(f"#{stats['rank']}" if stats["is_ranked"] else "Non classé"), inline=True)
        e.add_field(name="XP", value=f"{stats_service.format_number(stats['current_level_xp'])}/{stats_service.format_number(stats['required_xp'])}", inline=True)
        e.add_field(name="Progression", value=f"{stats['progress_pct']}%", inline=False)
        e.add_field(name="🎭 Prochain rôle", value=self._next_role_text(stats), inline=False)
        e.set_footer(text=settings.get("footer", DEFAULT_STATS_SETTINGS["footer"]))
        return e

    async def build_level_panneau(self, guild: discord.Guild, member: discord.Member) -> panels.Panneau:
        """Fiche de niveau composée.

        build_level_embed reste : une vue qui rafraichit son message ne peut pas
        remplacer un embed par un panneau Components V2. Ce constructeur sert la
        commande, l'autre sert le panneau interactif.
        """
        stats = await stats_service.get_member_statistics(self.bot, guild, member)
        nombre = stats_service.format_number
        restant = max(0, stats["required_xp"] - stats["current_level_xp"])

        progression = [
            panels.Ligne("Niveau", str(stats["current_level"])),
            panels.Ligne("XP", f"{nombre(stats['current_level_xp'])} / {nombre(stats['required_xp'])}"),
            panels.Ligne("Avancement", f"{stats['progress_pct']} %"),
            panels.Ligne("Restant", f"{nombre(restant)} XP"),
        ]

        # La barre est un repere visuel immediat, la ou un pourcentage demande un effort.
        barre = stats_service.progress_bar(
            stats["current_level_xp"], stats["required_xp"], length=18,
            emoji_filled="█", emoji_empty="░",
        )

        activite = [
            panels.Ligne("Messages", nombre(stats.get("message_count", 0))),
            panels.Ligne(
                "Classement", f"#{stats['rank']}" if stats["is_ranked"] else "Non classé"
            ),
        ]
        if stats.get("voice_seconds"):
            activite.append(
                panels.Ligne("En vocal", stats_service.format_duration(stats["voice_seconds"]))
            )

        sections = [
            panels.Section("Progression", progression, aligne=True),
            panels.Section("Avancement", texte=f"`{barre}`"),
            panels.Section("Activité", activite, aligne=True),
            panels.Section("Prochain rôle", [panels.Ligne("Palier", self._next_role_text(stats))]),
        ]

        return panels.Panneau(
            titre="SentriX — Niveau",
            sous_titre=f"{member.mention} · niveau **{stats['current_level']}**, "
                       f"encore **{nombre(restant)} XP** avant le suivant",
            kind="brand",
            vignette=member.display_avatar.url,
            sections=sections,
            pied="SentriX • Niveaux",
        )

    async def build_economy_embed(self, guild: discord.Guild, member: discord.Member) -> discord.Embed:
        settings = await self.bot.db.get_stats_settings(guild.id)
        stats = await stats_service.get_member_statistics(self.bot, guild, member)
        ranks = await stats_service.get_category_ranks(self.bot, guild.id, stats)
        eco_emoji = settings.get("economy_emoji", "🪙")
        bal_row = await self.bot.db.get_balance(guild.id, member.id)
        last_daily = bal_row["last_daily"] if bal_row else 0
        inv_rows = await self.bot.db.fetchall(
            "SELECT item_name, quantity FROM inventory WHERE guild_id = ? AND user_id = ? ORDER BY quantity DESC LIMIT 5",
            (guild.id, member.id),
        )
        e = discord.Embed(title=f"💰 Économie de {member.display_name}", color=settings["color"], timestamp=discord.utils.utcnow())
        e.set_thumbnail(url=member.display_avatar.url)
        e.add_field(name="Portefeuille", value=f"{stats_service.format_number(stats['wallet'])} {eco_emoji}", inline=True)
        e.add_field(name="Banque", value=f"{stats_service.format_number(stats['bank'])} 🏦", inline=True)
        e.add_field(name="Total", value=f"{stats_service.format_number(stats['total_money'])} {eco_emoji}", inline=True)
        e.add_field(name="Classement économique", value=f"#{ranks['economy_rank']}", inline=True)
        e.add_field(
            name="Dernière récompense quotidienne",
            value=f"<t:{last_daily}:R>" if last_daily else "Jamais réclamée",
            inline=True,
        )
        items_text = "\n".join(f"• {r['item_name']} × {stats_service.format_number(r['quantity'])}" for r in inv_rows) or "Inventaire vide."
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
        # Correction : /stats enchaîne une dizaine de requêtes (get_member_statistics
        # interroge levels, message_counts, voice_totals, voice_sessions, economy,
        # réputation, level_roles...). Sans defer(), Discord n'attend que 3 secondes avant
        # d'afficher "Cette interaction a échoué" à l'utilisateur — c'est très exactement
        # ce qui donnait l'impression que /stats et /level "ne se chargent pas" ou "prennent
        # trop de temps" : le bot répondait bien, mais souvent trop tard pour l'interaction
        # slash d'origine. defer() donne au bot jusqu'à 15 minutes pour répondre.
        if ctx.interaction:
            await ctx.defer()
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
        # Même correction que _send_stats : plusieurs requêtes DB enchaînées, il faut
        # deferer avant que Discord ne considère l'interaction comme expirée.
        if ctx.interaction:
            await ctx.defer()
        membre = membre or ctx.author
        settings = await self.bot.db.get_stats_settings(ctx.guild.id)
        try:
            if not await self._can_view(ctx, membre, settings):
                return await ctx.send(embed=embeds.error("La consultation des statistiques d'un autre membre est désactivée sur ce serveur."))
            panneau = await self.build_level_panneau(ctx.guild, membre)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            return await ctx.send(embed=embeds.error("Impossible de récupérer le niveau pour le moment (erreur Discord)."))
        except Exception:
            return await ctx.send(embed=embeds.error("Une erreur est survenue en préparant ce niveau."))
        await panels.envoyer(ctx, panneau)

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
        """Classement des niveaux, compose.

        L'ancien rendu etait une liste de dix lignes dans un seul bloc. Le podium
        se confondait avec le reste, et personne ne voyait sa propre position —
        la premiere chose qu'on cherche dans un classement.
        """
        if ctx.interaction:
            await ctx.defer()
        rows = await self.bot.db.fetchall(
            "SELECT * FROM levels WHERE guild_id = ? ORDER BY level DESC, xp DESC LIMIT 50",
            (ctx.guild.id,),
        )
        classement = []
        for row in rows:
            # Un membre absent du cache Discord n'a pas forcement quitte le serveur :
            # on l'affiche avec un identifiant de secours plutot que de le faire
            # disparaitre. On n'exclut que les bots confirmes.
            membre = ctx.guild.get_member(row["user_id"])
            if membre is not None and membre.bot:
                continue
            nom = membre.display_name if membre else f"Utilisateur {row['user_id']}"
            classement.append((row["user_id"], nom, int(row["level"]), int(row["xp"])))

        if not classement:
            return await panels.envoyer(
                ctx,
                panels.Panneau(
                    titre="SentriX — Classement des niveaux",
                    sous_titre="Personne n'a encore gagné d'XP sur ce serveur.",
                    kind="brand",
                    sections=[
                        panels.Section(
                            "Comment démarrer",
                            [
                                panels.Ligne("Écrivez", "L'XP se gagne en participant aux discussions"),
                                panels.Ligne("`+level`", "Voir votre progression"),
                            ],
                        )
                    ],
                    pied="SentriX • Niveaux",
                ),
            )

        nombre = stats_service.format_number
        medailles = ("1er", "2e", "3e")
        podium = [
            panels.Ligne(
                medailles[i],
                f"**{nom}** · niveau **{niveau}**",
                indice=f"{nombre(xp)} XP",
            )
            for i, (_uid, nom, niveau, xp) in enumerate(classement[:3])
        ]
        suite = [
            panels.Ligne(f"{i}", f"{nom} · niveau {niveau}")
            for i, (_uid, nom, niveau, _xp) in enumerate(classement[3:10], start=4)
        ]

        sections = [panels.Section("Podium", podium)]
        if suite:
            sections.append(panels.Section("Suivants", suite, aligne=True))

        # La position du demandeur : la premiere chose qu'on cherche.
        rang = next(
            (i for i, (uid, *_r) in enumerate(classement, start=1) if uid == ctx.author.id), None
        )
        if rang is not None:
            _uid, _nom, niveau, xp = classement[rang - 1]
            sections.append(
                panels.Section(
                    "Votre position",
                    [
                        panels.Ligne("Rang", f"**#{rang}** sur {len(classement)}"),
                        panels.Ligne("Niveau", str(niveau)),
                        panels.Ligne("XP", nombre(xp)),
                    ],
                    aligne=True,
                )
            )
        else:
            sections.append(
                panels.Section(
                    "Votre position",
                    [panels.Ligne("Non classé", "Écrivez quelques messages pour apparaître ici")],
                )
            )

        await panels.envoyer(
            ctx,
            panels.Panneau(
                titre="SentriX — Classement des niveaux",
                sous_titre=f"**{len(classement)}** membre(s) classé(s) sur {ctx.guild.name}.",
                kind="brand",
                sections=sections,
                pied="SentriX • Niveaux",
            ),
        )

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
        await self.bot.db.execute(
            "UPDATE levels SET xp = ?, updated_at = ? WHERE guild_id = ? AND user_id = ?",
            (max(0, xp), now(), ctx.guild.id, membre.id),
        )
        stats_service.invalidate_rank_cache(self.bot, ctx.guild.id, membre.id)
        await ctx.send(embed=embeds.success(f"XP de {membre.mention} défini à **{max(0, xp)}**."))

    @commands.hybrid_command(name="add-xp", description="[Admin] Ajouter de l'XP à un membre.", with_app_command=False)
    @app_commands.describe(membre="Le membre visé", xp="La quantité d'XP à ajouter")
    @checks.is_owner_or_admin_for("configuration")
    async def add_xp(self, ctx: commands.Context, membre: discord.Member, xp: int):
        if membre.bot:
            return await ctx.send(embed=embeds.error("Un bot ne peut pas avoir d'XP."))
        new_xp, level, leveled_up = await self._apply_xp_delta(ctx.guild.id, membre.id, xp)
        suffix = f" — passe au niveau **{level}** 🎉" if leveled_up else ""
        await ctx.send(embed=embeds.success(f"**{xp} XP** ajoutés à {membre.mention} (XP actuelle : {new_xp}, niveau {level}){suffix}."))

    @commands.hybrid_command(name="reset-levels", description="[Admin] Réinitialiser tous les niveaux du serveur.", with_app_command=False)
    @checks.is_owner_or_admin_for("configuration")
    async def reset_levels(self, ctx: commands.Context):
        await self.bot.db.execute("DELETE FROM levels WHERE guild_id = ?", (ctx.guild.id,))
        stats_service.invalidate_rank_cache(self.bot, ctx.guild.id)
        await ctx.send(embed=embeds.success("Tous les niveaux du serveur ont été réinitialisés."))

    # ---------------------------------------------------------------- DIAGNOSTIC NIVEAUX

    async def _level_diagnosis(self, guild_id: int, user_id: int) -> dict:
        """Lecture SEULE — ne crée ni ne modifie jamais la ligne du membre. Utilisée par
        +levelcheck (affichage) et +levelrepair (pour savoir s'il y a réellement quelque
        chose à réparer avant de proposer une confirmation)."""
        row = await self.bot.db.fetchone(
            "SELECT * FROM levels WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        )
        found = row is not None
        level = row["level"] if found else 0
        xp = row["xp"] if found else 0
        updated_at = row["updated_at"] if (found and "updated_at" in row.keys()) else 0
        needed = stats_service.xp_required_for_level(level)
        total_xp = stats_service.total_xp_for(level, xp)

        db_issues = []
        if xp < 0:
            db_issues.append("XP négative")
        if level < 0:
            db_issues.append("niveau négatif")
        if xp >= needed:
            db_issues.append(f"XP actuelle ({xp}) ≥ XP nécessaire ({needed}) pour ce niveau — le niveau aurait dû monter")
        db_coherent = found and not db_issues

        cache = getattr(self.bot, "_rank_cache", None)
        cached_entry = cache.get((guild_id, user_id)) if cache else None
        cache_coherent = True
        if cached_entry is not None and found:
            fresh_row = await self.bot.db.fetchone(
                "SELECT COUNT(*) AS n FROM levels WHERE guild_id = ? AND (level > ? OR (level = ? AND xp > ?))",
                (guild_id, level, level, xp),
            )
            fresh_rank = (fresh_row["n"] if fresh_row else 0) + 1
            cache_coherent = cached_entry[1] == fresh_rank

        return {
            "found": found, "level": level, "xp": xp, "needed": needed, "total_xp": total_xp,
            "updated_at": updated_at, "db_coherent": db_coherent, "db_issues": db_issues,
            "cache_coherent": cache_coherent,
        }

    @commands.hybrid_command(name="levelcheck", description="[Admin] Diagnostic en lecture seule du niveau d'un membre.", with_app_command=False)
    @app_commands.describe(membre="Le membre à diagnostiquer")
    @checks.is_owner_or_admin_for("configuration")
    async def levelcheck(self, ctx: commands.Context, membre: discord.Member):
        # Diagnostic pur : AUCUNE écriture, même pas ensure_level() (on ne veut pas créer
        # une ligne juste en la consultant — ça fausserait "ligne trouvée").
        diag = await self._level_diagnosis(ctx.guild.id, membre.id)
        e = embeds.neutral("🔍 Diagnostic niveau", "")
        e.add_field(name="Membre", value=membre.mention, inline=True)
        e.add_field(name="Serveur", value=ctx.guild.name, inline=True)
        e.add_field(name="Ligne trouvée", value="● Oui" if diag["found"] else "○ Non (le membre n'a encore jamais gagné d'XP ici)", inline=False)
        e.add_field(name="Niveau", value=str(diag["level"]), inline=True)
        e.add_field(name="XP totale (cumulée)", value=stats_service.format_number(diag["total_xp"]), inline=True)
        e.add_field(name="XP actuelle (niveau en cours)", value=stats_service.format_number(diag["xp"]), inline=True)
        e.add_field(name="XP nécessaire (prochain niveau)", value=stats_service.format_number(diag["needed"]), inline=True)
        e.add_field(name="Cache", value="● Cohérent" if diag["cache_coherent"] else "⚠️ Incohérent (sera corrigé automatiquement sous 20s)", inline=True)
        if diag["db_coherent"]:
            db_value = "● Cohérente"
        elif not diag["found"]:
            db_value = "➖ Aucune ligne à vérifier"
        else:
            db_value = "⚠️ " + " ; ".join(diag["db_issues"])
        e.add_field(name="Base de données", value=db_value, inline=True)
        if diag["found"] and diag["updated_at"]:
            e.add_field(name="Dernière mise à jour", value=f"<t:{diag['updated_at']}:R>", inline=True)
        else:
            e.add_field(name="Dernière mise à jour", value="Inconnue (ligne créée avant l'ajout de ce suivi, ou jamais mise à jour)", inline=True)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="levelrepair", description="[Admin] Réparer une incohérence certaine du niveau d'un membre (après confirmation).", with_app_command=False)
    @app_commands.describe(membre="Le membre à réparer")
    @checks.is_owner_or_admin_for("configuration")
    async def levelrepair(self, ctx: commands.Context, membre: discord.Member):
        diag = await self._level_diagnosis(ctx.guild.id, membre.id)
        if not diag["found"]:
            return await ctx.send(embed=embeds.info("Aucune ligne de niveau pour ce membre — rien à réparer."))
        if diag["db_coherent"]:
            return await ctx.send(embed=embeds.success("Aucune incohérence détectée pour ce membre — rien à réparer."))

        # Seule réparation possible : recalculer (niveau, xp du niveau) à partir de l'XP
        # TOTALE déjà accumulée (total_xp_for/calculate_level_from_total_xp), donc AUCUNE
        # perte d'XP — on ne fait que redistribuer le même total entre niveau et xp
        # relative. Jamais de remise à zéro.
        total_xp = diag["total_xp"]
        new_level, new_xp, _needed = stats_service.calculate_level_from_total_xp(total_xp)

        view = _LevelRepairConfirmView(author_id=ctx.author.id)
        preview = (
            f"**Avant** — niveau {diag['level']}, XP {stats_service.format_number(diag['xp'])} "
            f"(incohérence : {' ; '.join(diag['db_issues'])})\n"
            f"**Après** — niveau {new_level}, XP {stats_service.format_number(new_xp)}\n"
            f"XP totale conservée à l'identique : {stats_service.format_number(total_xp)}."
        )
        msg = await ctx.send(embed=embeds.warning(f"Confirmer la réparation du niveau de {membre.mention} ?\n\n{preview}"), view=view)
        view.message = msg
        await view.wait()
        if not view.confirmed:
            return
        await self.bot.db.execute(
            "UPDATE levels SET xp = ?, level = ?, updated_at = ? WHERE guild_id = ? AND user_id = ?",
            (new_xp, new_level, now(), ctx.guild.id, membre.id),
        )
        stats_service.invalidate_rank_cache(self.bot, ctx.guild.id, membre.id)
        try:
            await msg.edit(embed=embeds.success(f"Niveau de {membre.mention} réparé : niveau **{new_level}**, XP **{stats_service.format_number(new_xp)}** (XP totale conservée)."), view=None)
        except discord.HTTPException:
            pass

    @commands.hybrid_command(name="profile", description="Afficher votre profil communautaire.")
    @app_commands.describe(membre="Le membre visé (optionnel)")
    async def profile(self, ctx: commands.Context, membre: discord.Member = None):
        # Première commande migrée vers utils/design_system (Phase 2) : contrairement à
        # /stats et /level, /profile n'avait pas de couleur/footer pilotés par
        # +statsconfig — elle peut donc adopter le nouveau système sans rien casser de
        # déjà testé/approuvé. /stats et /level restent inchangées pour l'instant (voir
        # rapport de Phase 2 envoyé à Jayden).
        # Même correction que _send_stats/_send_level : get_member_statistics() enchaîne
        # une dizaine de requêtes, il faut deferer avant l'expiration à 3s de l'interaction.
        if ctx.interaction:
            await ctx.defer()
        membre = membre or ctx.author
        bio_row = await self.bot.db.fetchone(
            "SELECT * FROM profiles WHERE guild_id = ? AND user_id = ?", (ctx.guild.id, membre.id)
        )
        settings = await self.bot.db.get_stats_settings(ctx.guild.id)
        design = await self.bot.db.get_design_settings(ctx.guild.id)
        try:
            stats = await stats_service.get_member_statistics(self.bot, ctx.guild, membre)
        except Exception:
            return await ctx.send(embed=embeds.error("Une erreur est survenue en préparant ce profil."))
        eco_emoji = settings.get("economy_emoji", "🪙")
        style = design_system.CATEGORY_STYLES["levels"]
        e = design_system.create_embed(
            title=f"🪪 Profil de {membre.display_name}",
            description=f"{membre.mention} • Niveau **{stats['current_level']}**"
                        + (f" • Rang **#{stats['rank']}**" if stats["is_ranked"] else " • Non classé"),
            colour=design.get("primary_color", style["colour"]),
            user=membre if design.get("show_avatars", True) else None,
            thumbnail=membre.display_avatar.url if design.get("show_avatars", True) else None,
            footer=design.get("footer"),
        )
        e.add_field(name="📈 Niveau", value=f"**{stats['current_level']}**", inline=True)
        e.add_field(name="💬 Messages", value=stats_service.format_number(stats["message_count"]), inline=True)
        e.add_field(name="🔊 Temps vocal", value=stats_service.format_duration(stats["voice_time"]), inline=True)
        if settings.get("show_economy", True):
            e.add_field(
                name="💰 Économie",
                value=(
                    f"Portefeuille : {stats_service.format_number(stats['wallet'])} {eco_emoji}\n"
                    f"Banque : {stats_service.format_number(stats['bank'])} 🏦\n"
                    f"Total : {stats_service.format_number(stats['total_money'])} {eco_emoji}"
                ),
                inline=True,
            )
        if settings.get("show_reputation", True):
            e.add_field(name="⭐ Réputation", value=f"{stats_service.format_number(stats['reputation'])} point(s)", inline=True)
        e.add_field(name="📝 Bio", value=(bio_row["bio"] if bio_row and bio_row["bio"] else "Aucune bio définie."), inline=False)
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

    # -------------------------------------------------------------- Réputation

    @commands.hybrid_command(name="rep", description="Donner un point de réputation à un membre.")
    @app_commands.describe(membre="Le membre à qui donner un point de réputation", raison="Raison (optionnelle)")
    async def rep(self, ctx: commands.Context, membre: discord.Member, *, raison: str = ""):
        if membre.id == ctx.author.id:
            return await ctx.send(embed=embeds.error("Vous ne pouvez pas vous donner de la réputation à vous-même."))
        if membre.bot:
            return await ctx.send(embed=embeds.error("Vous ne pouvez pas donner de la réputation à un bot."))
        settings = await self.bot.db.get_stats_settings(ctx.guild.id)
        cooldown = settings.get("reputation_cooldown", 86400)
        try:
            ok, remaining = await self.bot.db.give_reputation(ctx.guild.id, ctx.author.id, membre.id, cooldown, raison[:200])
        except Exception:
            return await ctx.send(embed=embeds.error("Une erreur est survenue, réessayez."))
        if not ok:
            h, m = remaining // 3600, (remaining % 3600) // 60
            return await ctx.send(embed=embeds.warning(f"Vous devez attendre encore **{h}h{m:02d}m** avant de redonner un point de réputation."))
        total = await self.bot.db.get_reputation(ctx.guild.id, membre.id)
        await ctx.send(embed=embeds.success(f"⭐ Vous avez donné un point de réputation à {membre.mention} (total : **{stats_service.format_number(total)}**)."))

    @commands.hybrid_command(name="reputation", description="Afficher la réputation d'un membre et votre temps d'attente.")
    @app_commands.describe(membre="Le membre visé (optionnel)")
    async def reputation_cmd(self, ctx: commands.Context, membre: discord.Member = None):
        membre = membre or ctx.author
        settings = await self.bot.db.get_stats_settings(ctx.guild.id)
        total = await self.bot.db.get_reputation(ctx.guild.id, membre.id)
        remaining = await self.bot.db.get_reputation_cooldown_remaining(ctx.guild.id, ctx.author.id, settings.get("reputation_cooldown", 86400))
        e = embeds.neutral(f"⭐ Réputation de {membre.display_name}", f"{stats_service.format_number(total)} point(s)")
        if remaining > 0:
            h, m = remaining // 3600, (remaining % 3600) // 60
            e.add_field(name="Votre prochain +rep disponible dans", value=f"{h}h{m:02d}m", inline=False)
        else:
            e.add_field(name="Votre prochain +rep", value="Disponible maintenant", inline=False)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="repleaderboard", description="Afficher le classement de réputation.")
    async def repleaderboard(self, ctx: commands.Context):
        if ctx.interaction:
            await ctx.defer()
        rows = await self.bot.db.fetchall(
            "SELECT * FROM profiles WHERE guild_id = ? AND reputation > 0 ORDER BY reputation DESC LIMIT 15", (ctx.guild.id,)
        )
        if not rows:
            return await ctx.send(embed=embeds.info("Aucune donnée de réputation pour l'instant."))
        lines = []
        rank = 0
        for r in rows:
            member = ctx.guild.get_member(r["user_id"])
            if member is not None and member.bot:
                continue
            name = member.display_name if member else f"Utilisateur {r['user_id']}"
            rank += 1
            if rank > 10:
                break
            lines.append(f"**{rank}.** {name} — {stats_service.format_number(r['reputation'])} point(s)")
        if not lines:
            return await ctx.send(embed=embeds.info("Aucune donnée de réputation pour l'instant."))
        await ctx.send(embed=embeds.neutral("⭐ Classement de réputation", "\n".join(lines)))

    @commands.hybrid_command(name="repconfig", description="[Admin] Configurer le cooldown de réputation (en heures).", with_app_command=False)
    @app_commands.describe(heures="Nombre d'heures entre deux +rep")
    @checks.is_owner_or_admin_for("configuration")
    async def repconfig(self, ctx: commands.Context, heures: int):
        if heures <= 0:
            return await ctx.send(embed=embeds.error("Le cooldown doit être positif (en heures)."))
        await self.bot.db.set_stats_settings(ctx.guild.id, {"reputation_cooldown": heures * 3600})
        await ctx.send(embed=embeds.success(f"Cooldown de réputation défini à **{heures}h**."))

    @commands.hybrid_command(name="repadd", description="[Staff] Ajouter des points de réputation à un membre.", with_app_command=False)
    @app_commands.describe(membre="Le membre visé", nombre="Le nombre de points à ajouter", raison="Raison (optionnelle)")
    @checks.is_owner_or_admin_for("configuration")
    async def repadd(self, ctx: commands.Context, membre: discord.Member, nombre: int, *, raison: str = ""):
        if nombre <= 0:
            return await ctx.send(embed=embeds.error("Le nombre doit être positif."))
        total = await self.bot.db.adjust_reputation(ctx.guild.id, ctx.author.id, membre.id, nombre, raison[:200] or "Ajout manuel (staff)")
        await ctx.send(embed=embeds.success(f"**+{nombre}** réputation pour {membre.mention} (total : **{stats_service.format_number(total)}**)."))

    @commands.hybrid_command(name="repremove", description="[Staff] Retirer des points de réputation à un membre (abus).", with_app_command=False)
    @app_commands.describe(membre="Le membre visé", nombre="Le nombre de points à retirer", raison="Raison (optionnelle)")
    @checks.is_owner_or_admin_for("configuration")
    async def repremove(self, ctx: commands.Context, membre: discord.Member, nombre: int, *, raison: str = ""):
        if nombre <= 0:
            return await ctx.send(embed=embeds.error("Le nombre doit être positif."))
        total = await self.bot.db.adjust_reputation(ctx.guild.id, ctx.author.id, membre.id, -nombre, raison[:200] or "Retrait manuel (staff, abus)")
        await ctx.send(embed=embeds.success(f"**-{nombre}** réputation pour {membre.mention} (total : **{stats_service.format_number(total)}**)."))

    @commands.hybrid_command(name="represet", description="[Staff] Réinitialiser la réputation d'un membre à zéro.", with_app_command=False)
    @app_commands.describe(membre="Le membre visé")
    @checks.is_owner_or_admin_for("configuration")
    async def represet(self, ctx: commands.Context, membre: discord.Member):
        await self.bot.db.reset_reputation(ctx.guild.id, ctx.author.id, membre.id)
        await ctx.send(embed=embeds.success(f"Réputation de {membre.mention} réinitialisée à **0**."))

    @commands.hybrid_command(name="rephistory", description="[Staff] Afficher l'historique de réputation d'un membre.", with_app_command=False)
    @app_commands.describe(membre="Le membre visé")
    @checks.is_owner_or_admin_for("configuration")
    async def rephistory(self, ctx: commands.Context, membre: discord.Member):
        rows = await self.bot.db.get_reputation_history(ctx.guild.id, membre.id)
        if not rows:
            return await ctx.send(embed=embeds.info(f"Aucun historique de réputation pour {membre.display_name}."))
        lines = []
        for r in rows:
            giver = ctx.guild.get_member(r["giver_id"])
            giver_name = giver.display_name if giver else f"Utilisateur {r['giver_id']}"
            sign = "+" if r["amount"] >= 0 else ""
            reason = f" — {r['reason']}" if r["reason"] else ""
            lines.append(f"<t:{r['created_at']}:R> **{sign}{r['amount']}** par {giver_name}{reason}")
        await ctx.send(embed=embeds.neutral(f"📜 Historique de réputation de {membre.display_name}", "\n".join(lines)))

    @commands.hybrid_command(name="voice-time", description="Afficher le temps passé en vocal par un membre.", with_app_command=False)
    @app_commands.describe(membre="Le membre visé (optionnel)")
    async def voice_time(self, ctx: commands.Context, membre: discord.Member = None):
        if ctx.interaction:
            await ctx.defer()
        membre = membre or ctx.author
        try:
            stats = await stats_service.get_member_statistics(self.bot, ctx.guild, membre)
        except Exception:
            return await ctx.send(embed=embeds.error("Impossible de récupérer le temps vocal pour le moment."))
        await ctx.send(embed=embeds.info(f"🔊 {membre.display_name} a passé **{stats_service.format_duration(stats['voice_time'])}** en vocal."))

    async def _open_statsconfig(self, ctx: commands.Context, category: str = "appearance"):
        settings = await self.bot.db.get_stats_settings(ctx.guild.id)
        conf = await self.bot.db.get_guild_config(ctx.guild.id)
        view = StatsConfigView(self, ctx.guild, ctx.author.id, settings)
        if conf and conf["xp_channel_disabled"]:
            view.pending["_xp_channel_disabled"] = conf["xp_channel_disabled"]
        view.pending["_level_channel"] = conf["level_channel"] if conf else None
        view.category = category
        view.rebuild_items()
        embed = view.build_summary_embed()
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg

    @commands.hybrid_command(name="statsconfig", description="[Admin] Configurer l'apparence et le comportement de /stats et /level.", with_app_command=False)
    @checks.is_owner_or_admin_for("configuration")
    async def statsconfig(self, ctx: commands.Context):
        await self._open_statsconfig(ctx, "appearance")

    @commands.hybrid_command(name="levelroles", description="[Admin] Configurer les paliers de rôles de niveau.", with_app_command=False)
    @checks.is_owner_or_admin_for("configuration")
    async def levelroles(self, ctx: commands.Context):
        """Alias de +statsconfig ouvert directement sur la catégorie "Niveaux"."""
        await self._open_statsconfig(ctx, "levels")

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
