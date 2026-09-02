"""
Cog DESIGN — panneau de configuration +designsetup (Phase 1 de la refonte visuelle).

Ce panneau permet au staff de régler les couleurs, le footer, la barre de progression,
les avatars, le mode compact et les graphiques du futur système de design (voir
utils/design_system.py). En Phase 1, ces réglages sont uniquement ENREGISTRÉS — aucune
commande existante ne les utilise encore pour s'afficher (/stats, /level, /profile...
continuent d'utiliser utils/embeds.py et +statsconfig comme avant). La migration réelle
des commandes vers ce système se fera progressivement aux Phases 2 à 5, comme convenu
avec Jayden, pour ne jamais risquer de casser une commande qui fonctionne déjà.

Commande prefix-only (with_app_command=False) : le budget de commandes slash de SentriX
est déjà très serré (96/100), et ce panneau n'a pas besoin d'être une commande slash.
"""

import discord

from utils import embeds
from utils import sentrix_panels as panels
from discord.ext import commands

from utils import checks, design_system, visual_v5
from database.db import DEFAULT_DESIGN_SETTINGS


# =============================================================================
# Modals
# =============================================================================


def _reponse(titre: str, description: str, *, kind: str = "brand") -> discord.Embed:
    """Reponse au format canonique SentriX.

    Ce module repondait en texte nu : ni couleur d'intention, ni pied de page,
    ni barre d'identite, alors que le reste du bot en porte.
    """
    return embeds._base(titre, description, kind=kind)


class DesignColorsModal(discord.ui.Modal, title="Couleurs du système de design"):
    def __init__(self, view: "DesignSetupView"):
        super().__init__()
        self.view_ref = view
        p = view.pending
        self.primary = discord.ui.TextInput(label="Couleur principale (hex)", default=f"{p['primary_color']:06X}", max_length=6, min_length=6)
        self.secondary = discord.ui.TextInput(label="Couleur secondaire (hex)", default=f"{p['secondary_color']:06X}", max_length=6, min_length=6)
        self.success = discord.ui.TextInput(label="Couleur succès (hex)", default=f"{p['success_color']:06X}", max_length=6, min_length=6)
        self.warning = discord.ui.TextInput(label="Couleur avertissement (hex)", default=f"{p['warning_color']:06X}", max_length=6, min_length=6)
        self.danger = discord.ui.TextInput(label="Couleur erreur (hex)", default=f"{p['danger_color']:06X}", max_length=6, min_length=6)
        for item in (self.primary, self.secondary, self.success, self.warning, self.danger):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        fields = {
            "primary_color": self.primary.value,
            "secondary_color": self.secondary.value,
            "success_color": self.success.value,
            "warning_color": self.warning.value,
            "danger_color": self.danger.value,
        }
        parsed = {}
        for key, raw in fields.items():
            try:
                parsed[key] = int(str(raw).strip().lstrip("#"), 16)
            except ValueError:
                return await panels.envoyer(interaction.response, panels.depuis_embed(design_system.error_embed(f'Couleur invalide pour « {key} » — utilisez un code hexadécimal comme `5865F2`.', interaction.user)), ephemere=True)
        self.view_ref.pending.update(parsed)
        await self.view_ref.refresh(interaction)


class DesignAppearanceModal(discord.ui.Modal, title="Apparence générale"):
    def __init__(self, view: "DesignSetupView"):
        super().__init__()
        self.view_ref = view
        p = view.pending
        self.footer = discord.ui.TextInput(label="Texte du footer", default=p["footer"], max_length=100, required=True)
        for item in (self.footer,):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        self.view_ref.pending.update({
            "footer": str(self.footer.value),
        })
        await self.view_ref.refresh(interaction)


# =============================================================================
# Contrôles
# =============================================================================


class ThemePresetSelect(discord.ui.Select):
    """Trois identités complètes, appliquées sans saisir cinq codes couleur."""

    def __init__(self, view: "DesignSetupView"):
        self.view_ref = view
        current = visual_v5.resolve_theme(view.pending.get("theme_preset")) or "sentrix"
        options = [
            discord.SelectOption(
                label=data["label"],
                value=key,
                description=data["description"],
                default=key == current,
            )
            for key, data in visual_v5.THEME_PRESETS.items()
        ]
        super().__init__(placeholder="Choisir un thème visuel…", options=options, row=2)

    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]
        compact = bool(self.view_ref.pending.get("compact_mode", False))
        self.view_ref.pending.update(visual_v5.theme_settings(selected, compact_mode=compact))
        self.view_ref.rebuild_items()
        await self.view_ref.refresh(interaction)


class DesignBoolToggleButton(discord.ui.Button):
    def __init__(self, view: "DesignSetupView", key: str, label: str, row: int):
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


# =============================================================================
# Panneau principal
# =============================================================================

class DesignSetupView(design_system.SentriXView):
    """Panneau +designsetup — réglages regroupés sur un seul écran (contrairement à
    +statsconfig qui a plusieurs catégories) car le nombre de réglages est plus réduit.
    Hérite de design_system.SentriXView pour que ce nouveau système soit lui-même le
    premier à utiliser sa propre vue de base (auteur + staff, refus ephemeral, timeout)."""

    def __init__(self, cog: "Design", guild: discord.Guild, author_id: int, settings: dict, timeout: float = 300):
        super().__init__(author_id=author_id, allowed_staff=True, timeout=timeout)
        self.cog = cog
        self.guild = guild
        self.pending = dict(settings)
        self.rebuild_items()

    def rebuild_items(self):
        self.clear_items()

        colors_btn = discord.ui.Button(label="🎨 Modifier les couleurs", style=discord.ButtonStyle.primary, row=0)
        colors_btn.callback = self._open_colors_modal
        self.add_item(colors_btn)

        appearance_btn = discord.ui.Button(label="✏️ Modifier footer / emojis", style=discord.ButtonStyle.primary, row=0)
        appearance_btn.callback = self._open_appearance_modal
        self.add_item(appearance_btn)

        self.add_item(DesignBoolToggleButton(self, "show_avatars", "Avatars affichés", row=1))
        self.add_item(DesignBoolToggleButton(self, "compact_mode", "Mode compact", row=1))
        self.add_item(DesignBoolToggleButton(self, "charts_enabled", "Graphiques activés", row=1))
        self.add_item(DesignBoolToggleButton(self, "seasonal_theme", "Thème saisonnier", row=1))
        self.add_item(ThemePresetSelect(self))

        preview_btn = discord.ui.Button(label="👁️ Prévisualiser", style=discord.ButtonStyle.secondary, row=3)
        preview_btn.callback = self._preview
        save_btn = discord.ui.Button(label="💾 Enregistrer", style=discord.ButtonStyle.success, row=3)
        save_btn.callback = self._save
        reset_btn = discord.ui.Button(label="🔄 Réinitialiser", style=discord.ButtonStyle.danger, row=3)
        reset_btn.callback = self._reset
        cancel_btn = discord.ui.Button(label="○ Annuler", style=discord.ButtonStyle.secondary, row=3)
        cancel_btn.callback = self._cancel
        for b in (preview_btn, save_btn, reset_btn, cancel_btn):
            self.add_item(b)

    async def _open_colors_modal(self, interaction: discord.Interaction):
        await interaction.response.send_modal(DesignColorsModal(self))

    async def _open_appearance_modal(self, interaction: discord.Interaction):
        await interaction.response.send_modal(DesignAppearanceModal(self))

    def build_summary_embed(self) -> discord.Embed:
        p = self.pending
        theme_key = visual_v5.resolve_theme(p.get("theme_preset")) or "sentrix"
        theme = visual_v5.THEME_PRESETS[theme_key]
        # Apercu de la couleur que le serveur est en train de choisir : la teinte est
        # volontairement celle du serveur, pas une intention. On passe quand meme par
        # le constructeur canonique pour recuperer le pied de page et la barre.
        e = embeds._base("SentriX • Apparence", None, colour=int(p["primary_color"]))
        e.description = (
            "Choisis une identité complète ou règle chaque couleur. "
            "Les nouveaux panneaux utilisent ces préférences automatiquement."
        )
        e.add_field(name="Thème", value=theme["label"], inline=True)
        e.add_field(name="Saisons", value="Actif" if p.get("seasonal_theme", True) else "Inactif", inline=True)
        e.add_field(
            name="🎨 Couleurs",
            value=(
                f"Principale : #{p['primary_color']:06X}\n"
                f"Secondaire : #{p['secondary_color']:06X}\n"
                f"Succès : #{p['success_color']:06X}\n"
                f"Avertissement : #{p['warning_color']:06X}\n"
                f"Erreur : #{p['danger_color']:06X}"
            ),
            inline=False,
        )
        e.add_field(name="✏️ Footer", value=p["footer"], inline=True)
        e.add_field(name="🖼️ Avatars affichés", value="Oui" if p.get("show_avatars", True) else "Non", inline=True)
        e.add_field(name="📐 Mode compact", value="Oui" if p.get("compact_mode", False) else "Non", inline=True)
        e.add_field(name="📈 Graphiques activés", value="Oui" if p.get("charts_enabled", True) else "Non", inline=True)
        e.set_footer(text="SentriX • Enregistre pour appliquer les changements")
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
        p = self.pending
        embed = design_system.create_embed(
            title="Aperçu du thème",
            description="Aperçu de progression\n" + design_system.progress_bar(7, 10),
            colour=p["primary_color"],
            user=interaction.user if p.get("show_avatars", True) else None,
            footer=p["footer"],
        )
        await panels.envoyer(interaction.response, panels.depuis_embed(embed), ephemere=True)

    async def _save(self, interaction: discord.Interaction):
        await self.cog.bot.db.set_design_settings(self.guild.id, self.pending)
        embed = self.build_summary_embed()
        embed.set_footer(text="● Enregistré — ces réglages resteront après un redémarrage du bot.")
        await interaction.response.edit_message(embed=embed, view=self)

    async def _reset(self, interaction: discord.Interaction):
        await self.cog.bot.db.reset_design_settings(self.guild.id)
        self.pending = dict(DEFAULT_DESIGN_SETTINGS)
        self.rebuild_items()
        embed = self.build_summary_embed()
        embed.set_footer(text="🔄 Réinitialisé aux valeurs par défaut et enregistré.")
        await interaction.response.edit_message(embed=embed, view=self)

    async def _cancel(self, interaction: discord.Interaction):
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True
        embed = design_system.info_embed("Configuration fermée — les modifications non enregistrées ont été abandonnées.", interaction.user)
        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()


# =============================================================================
# Cog
# =============================================================================

class Design(commands.Cog, name="Design"):
    """Panneau de configuration du système de design (Phase 1 uniquement)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(
        name="designsetup",
        description="[Admin] Configurer le système de design de SentriX (couleurs, footer, barres, options).",
        with_app_command=False,
    )
    @checks.is_owner_or_admin_for("configuration")
    async def designsetup(self, ctx: commands.Context):
        settings = await self.bot.db.get_design_settings(ctx.guild.id)
        view = DesignSetupView(self, ctx.guild, ctx.author.id, settings)
        embed = view.build_summary_embed()
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg


async def setup(bot: commands.Bot):
    await bot.add_cog(Design(bot))
