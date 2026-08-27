"""Ameliore l'experience de ``/setup`` sans modifier son coeur historique.

Objectifs :
- rendre la page d'accueil et les pages de categorie plus aerées ;
- ajouter un diagnostic rapide et un bouton d'actualisation ;
- rendre les quatre profils de ``+setup auto`` accessibles depuis le panneau avec une
  confirmation explicite avant toute creation de salon ;
- conserver exactement les controles d'autorisation, la persistance et les sauvegardes
  deja geres par ``cogs.configuration``.

Cette couche est volontairement additive : aucun schema de base de donnees, aucune
permission et aucun callback historique n'est remplace.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

import config
from utils import embeds

logger = logging.getLogger("bot.setup-experience-v2")

PROFILE_LABELS = {
    "community": "Communauté",
    "gaming": "Gaming",
    "support": "Support",
    "creator": "Créateur",
}


async def _can_use_setup(view, interaction: discord.Interaction) -> bool:
    configuration = view.bot.get_cog("Configuration")
    checker = getattr(configuration, "_can_use_setup", None)
    if checker is not None:
        return bool(await checker(interaction, view.author_id, view.guild_id))

    if interaction.user.id == view.author_id or interaction.user.id in config.OWNER_IDS:
        return True
    member = interaction.user
    if isinstance(member, discord.Member) and member.guild_permissions.administrator:
        return True
    if not interaction.response.is_done():
        await interaction.response.send_message(
            embed=embeds.error("Vous n'êtes pas autorisé à modifier cette configuration."),
            ephemeral=True,
        )
    return False


async def _refresh_setup_message(parent_view) -> None:
    """Rafraichit le panneau public si le message existe encore."""
    guild = parent_view.bot.get_guild(parent_view.guild_id)
    if guild is None:
        return
    channel = guild.get_channel(parent_view.channel_id)
    if channel is None or not hasattr(channel, "fetch_message"):
        return
    try:
        message = await channel.fetch_message(parent_view.message_id)
        parent_view.page = -1
        parent_view.render_page()
        await parent_view.persist_session()
        await message.edit(embed=await parent_view.build_embed(), view=parent_view)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return


class AutoSetupConfirmView(discord.ui.View):
    """Confirmation ephemere avant d'executer un profil automatique existant."""

    def __init__(self, parent_view, profile: str, requester_id: int):
        super().__init__(timeout=60)
        self.parent_view = parent_view
        self.profile = profile
        self.requester_id = requester_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                embed=embeds.error("Cette confirmation appartient à un autre administrateur."),
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Confirmer", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _can_use_setup(self.parent_view, interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        platform = self.parent_view.bot.get_cog("PlatformV4")
        if platform is None or not hasattr(platform, "quick_setup"):
            await interaction.followup.send(
                embed=embeds.error("La configuration automatique se charge encore. Réessayez dans quelques secondes."),
                ephemeral=True,
            )
            return

        guild = self.parent_view.bot.get_guild(self.parent_view.guild_id)
        if guild is None:
            await interaction.followup.send(embed=embeds.error("Serveur introuvable."), ephemeral=True)
            return

        try:
            result = await platform.quick_setup(guild, interaction.user.id, self.profile)
        except Exception as exc:
            logger.exception("Echec setup auto depuis le panneau: %s", self.profile)
            detail = str(exc).strip() or "La configuration automatique a échoué."
            await interaction.followup.send(embed=embeds.error(detail[:900]), ephemeral=True)
            return

        created = result.get("created_channels", []) if isinstance(result, dict) else []
        created_count = len(created) if isinstance(created, (list, tuple, set)) else int(created or 0)
        missing = result.get("missing_permissions", []) if isinstance(result, dict) else []
        description = (
            f"Profil **{PROFILE_LABELS.get(self.profile, self.profile)}** appliqué.\n\n"
            f"**{created_count}** salon(s) créé(s) ou préparé(s)."
        )
        if missing:
            description += "\n\nPermissions à vérifier : " + ", ".join(str(item) for item in missing[:6])
        await interaction.followup.send(embed=embeds.success(description), ephemeral=True)
        await _refresh_setup_message(self.parent_view)
        self.stop()

    @discord.ui.button(label="Annuler", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=embeds.neutral("Configuration automatique annulée", "Aucune modification n'a été appliquée."),
            view=None,
        )
        self.stop()


async def _show_diagnostic(view, interaction: discord.Interaction) -> None:
    if not await _can_use_setup(view, interaction):
        return
    guild = view.bot.get_guild(view.guild_id)
    if guild is None or guild.me is None:
        return await interaction.response.send_message(
            embed=embeds.error("Impossible de lire l'état du serveur."), ephemeral=True
        )

    perms = guild.me.guild_permissions
    checks = [
        ("Gérer les salons", perms.manage_channels),
        ("Gérer les rôles", perms.manage_roles),
        ("Gérer les emojis", perms.manage_emojis_and_stickers),
        ("Voir les logs d'audit", perms.view_audit_log),
        ("Envoyer des messages", perms.send_messages),
        ("Intégrer des liens", perms.embed_links),
    ]
    lines = [f"{'●' if ok else '○'} **{label}**" for label, ok in checks]
    missing = sum(1 for _, ok in checks if not ok)

    regular_used = sum(1 for item in guild.emojis if not item.animated)
    animated_used = sum(1 for item in guild.emojis if item.animated)
    pending = len(getattr(view, "choices", {}) or {})
    auto_ready = view.bot.get_cog("PlatformV4") is not None

    state = "Prêt" if missing == 0 else f"{missing} permission(s) à corriger"
    e = embeds.neutral(
        "Diagnostic rapide du setup",
        f"**État : {state}**\n\n" + "\n".join(lines),
    )
    e.add_field(
        name="Capacité du serveur",
        value=(
            f"Salons : **{len(guild.channels)}**\n"
            f"Emojis statiques : **{regular_used}/{guild.emoji_limit}**\n"
            f"Emojis animés : **{animated_used}/{guild.emoji_limit}**"
        ),
        inline=True,
    )
    e.add_field(
        name="Session setup",
        value=(
            f"Modifications en attente : **{pending}**\n"
            f"Setup auto : **{'disponible' if auto_ready else 'chargement'}**\n"
            "Sauvegarde : **active**"
        ),
        inline=True,
    )
    e.add_field(
        name="Conseil",
        value=(
            "Corrigez d'abord les lignes ○. Elles peuvent empêcher la création de salons, "
            "rôles, logs ou emojis même si le reste du panneau fonctionne."
            if missing
            else "Les permissions principales de SentriX sont prêtes pour la configuration."
        ),
        inline=False,
    )
    await interaction.response.send_message(embed=e, ephemeral=True)


def install() -> bool:
    from cogs.configuration import SetupView

    if getattr(SetupView, "_sentrix_experience_v2", False):
        return True

    original_home_embed = SetupView._build_home_embed
    original_build_embed = SetupView.build_embed
    original_render_home = SetupView._render_home

    async def spacious_home_embed(self):
        e = await original_home_embed(self)
        e.description = (
            "Configurez SentriX sans quitter ce panneau.\n\n"
            "**1.** Choisissez une catégorie dans le menu.\n"
            "**2.** Modifiez uniquement ce dont vous avez besoin.\n"
            "**3.** Enregistrez, puis utilisez le diagnostic pour vérifier le serveur.\n\n"
            "Vous pouvez aussi lancer une configuration automatique avec un profil préparé."
        )
        if len(e.fields) < 24:
            e.insert_field_at(
                0,
                name="Accès rapide",
                value=(
                    "**Configuration manuelle** — menu principal ci-dessous\n"
                    "**Configuration automatique** — profils Communauté, Gaming, Support ou Créateur\n"
                    "**Diagnostic** — permissions, capacité et état de la session"
                ),
                inline=False,
            )
        e.set_footer(text="SentriX Setup • Les changements sensibles restent protégés par les permissions du serveur")
        return e

    async def spacious_build_embed(self):
        e = await original_build_embed(self)
        if self.page != -1:
            description = str(e.description or "").strip()
            if description:
                e.description = description + (
                    "\n\n────────────────────────\n"
                    "Les réglages de cette catégorie sont séparés pour éviter les modifications accidentelles."
                )
            e.set_footer(text="SentriX Setup • Accueil, Enregistrer, Résumé et Fermer restent disponibles")
        return e

    def expanded_render_home(self):
        original_render_home(self)

        auto_select = discord.ui.Select(
            placeholder="Configuration automatique — choisir un profil",
            options=[
                discord.SelectOption(
                    label="Communauté",
                    value="community",
                    description="Accueil, communauté et structure polyvalente",
                ),
                discord.SelectOption(
                    label="Gaming",
                    value="gaming",
                    description="Salons et structure adaptés à un serveur de jeu",
                ),
                discord.SelectOption(
                    label="Support",
                    value="support",
                    description="Organisation centrée sur l'aide et les tickets",
                ),
                discord.SelectOption(
                    label="Créateur",
                    value="creator",
                    description="Communauté autour d'un créateur et de ses annonces",
                ),
            ],
            row=2,
        )

        async def auto_callback(interaction: discord.Interaction):
            if not await _can_use_setup(self, interaction):
                return
            if not auto_select.values:
                return
            profile = auto_select.values[0]
            e = embeds.neutral(
                "Confirmer la configuration automatique",
                (
                    f"Profil choisi : **{PROFILE_LABELS.get(profile, profile)}**.\n\n"
                    "SentriX peut créer uniquement les éléments manquants prévus par ce profil. "
                    "Les réglages existants sont conservés autant que le service de setup le permet.\n\n"
                    "Confirmez pour continuer ou annulez sans rien modifier."
                ),
            )
            await interaction.response.send_message(
                embed=e,
                view=AutoSetupConfirmView(self, profile, interaction.user.id),
                ephemeral=True,
            )

        auto_select.callback = auto_callback
        self.add_item(auto_select)

        diagnostic = discord.ui.Button(
            label="Diagnostic",
            style=discord.ButtonStyle.secondary,
            row=3,
        )

        async def diagnostic_callback(interaction: discord.Interaction):
            await _show_diagnostic(self, interaction)

        diagnostic.callback = diagnostic_callback
        self.add_item(diagnostic)

        refresh = discord.ui.Button(
            label="Actualiser",
            style=discord.ButtonStyle.secondary,
            row=3,
        )

        async def refresh_callback(interaction: discord.Interaction):
            if not await _can_use_setup(self, interaction):
                return
            self.page = -1
            self.render_page()
            await self.persist_session()
            await interaction.response.edit_message(embed=await self.build_embed(), view=self)

        refresh.callback = refresh_callback
        self.add_item(refresh)

    SetupView._build_home_embed = spacious_home_embed
    SetupView.build_embed = spacious_build_embed
    SetupView._render_home = expanded_render_home
    SetupView._sentrix_experience_v2 = True
    logger.info("Experience /setup V2 installée : espace, diagnostic, actualisation et setup auto confirmé.")
    return True


class SetupExperienceV2(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        install()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SetupExperienceV2(bot))
    install()
