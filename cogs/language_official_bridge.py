"""Pont de langue pour les propriétaires officiels de +setup et +help.

La refonte du centre de configuration remplace volontairement l'ancien SetupView de
cogs.configuration. Le moteur FR/EN reste conservé, mais il doit désormais viser le
nouveau propriétaire cogs.setup_control_center au lieu de rebrancher une ancienne UI.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from . import language_runtime

logger = logging.getLogger("bot.language-official-bridge")


EN_REPLACEMENTS = (
    ("Bienvenue & départ", "Welcome & goodbye"),
    ("Niveaux & économie", "Levels & economy"),
    ("Centre de configuration", "Configuration center"),
    ("Control Center", "Control Center"),
    ("Choisissez une catégorie", "Choose a category"),
    ("Choisir une catégorie", "Choose a category"),
    ("Choisir une page du Control Center", "Choose a Control Center page"),
    ("Modération", "Moderation"),
    ("Sécurité", "Security"),
    ("Rôles", "Roles"),
    ("Niveaux", "Levels"),
    ("Économie", "Economy"),
    ("Notifications", "Notifications"),
    ("Bienvenue", "Welcome"),
    ("Départ", "Goodbye"),
    ("Configuration", "Configuration"),
    ("État", "Status"),
    ("État général", "Overall status"),
    ("Permissions SentriX", "SentriX permissions"),
    ("Permissions du bot", "Bot permissions"),
    ("Problèmes détectés", "Detected problems"),
    ("À corriger", "To fix"),
    ("Fonctions", "Features"),
    ("Protections", "Protections"),
    ("Types de logs", "Log types"),
    ("Récompenses", "Rewards"),
    ("Conservation", "Data retention"),
    ("Paramètres", "Settings"),
    ("Sources", "Sources"),
    ("Ajouter une source", "Add a source"),
    ("Avancé", "Advanced"),
    ("Accueil", "Home"),
    ("Actualiser", "Refresh"),
    ("Fermer", "Close"),
    ("Activer", "Enable"),
    ("Désactiver", "Disable"),
    ("Rôle staff", "Staff role"),
    ("Rôle mute", "Mute role"),
    ("Rôle warn", "Warn role"),
    ("Rôle automatique", "Automatic role"),
    ("Rôle vérifié", "Verified role"),
    ("Rôle membre principal", "Main member role"),
    ("Salon de bienvenue", "Welcome channel"),
    ("Salon de départ", "Goodbye channel"),
    ("Salon level-up", "Level-up channel"),
    ("Salon de notification", "Notification channel"),
    ("Rôle mentionné", "Mentioned role"),
    ("Choisir un type de log", "Choose a log type"),
    ("Choisir un type de ticket", "Choose a ticket type"),
    ("Choisir une notification", "Choose a notification"),
    ("Activer / désactiver ce log", "Enable / disable this log"),
    ("ACTIF", "ACTIVE"),
    ("INACTIF", "INACTIVE"),
    ("NON CONFIGURÉ", "NOT CONFIGURED"),
    ("ERREUR DE CONFIGURATION", "CONFIGURATION ERROR"),
    ("Non configuré", "Not configured"),
    ("Introuvable", "Missing"),
    ("MANQUANT", "MISSING"),
    ("Configurée", "Configured"),
    ("Personnalisé", "Custom"),
    ("Par défaut", "Default"),
)


def _english(text: object | None) -> str | None:
    if text is None:
        return None
    value = str(text)
    try:
        translated = language_runtime._english_setup_text(value)
        value = str(translated if translated is not None else value)
    except Exception:
        pass
    for source, target in EN_REPLACEMENTS:
        value = value.replace(source, target)
    return value


def _is_english(view) -> bool:
    guild = getattr(view, "guild", None)
    guild_id = getattr(guild, "id", None)
    return language_runtime.cached_language(view.bot, guild_id) == language_runtime.LANG_EN


class OfficialLanguageSelect(discord.ui.Select):
    def __init__(self, owner):
        self.owner = owner
        english = _is_english(owner)
        current = language_runtime.LANG_EN if english else language_runtime.LANG_FR
        super().__init__(
            placeholder="Server language" if english else "Langue du serveur",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label="Français",
                    value=language_runtime.LANG_FR,
                    description="Interfaces et noms de commandes en français",
                    default=current == language_runtime.LANG_FR,
                ),
                discord.SelectOption(
                    label="English",
                    value=language_runtime.LANG_EN,
                    description="Interfaces and command names in English",
                    default=current == language_runtime.LANG_EN,
                ),
            ],
            row=2,
            custom_id="sentrix:setup:official:language",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return
        if not (
            interaction.user.guild_permissions.administrator
            or interaction.user.id == interaction.guild.owner_id
        ):
            return await interaction.response.send_message(
                "Permission Administrateur requise. / Administrator permission required.",
                ephemeral=True,
            )
        await language_runtime.set_language(self.owner.bot, interaction.guild.id, self.values[0])
        await self.owner.refresh(interaction)


def _translate_component(item) -> None:
    if isinstance(item, discord.ui.Button):
        if item.label:
            item.label = _english(item.label)
        return
    if isinstance(item, discord.ui.Select):
        if item.placeholder:
            item.placeholder = _english(item.placeholder)
        for option in getattr(item, "options", ()):
            option.label = _english(option.label) or option.label
            if option.description:
                option.description = _english(option.description)


def _patch_setup(*, force: bool = False) -> None:
    from . import setup_control_center

    view_cls = setup_control_center.SetupView
    if force:
        view_cls._sentrix_official_language_bridge = False
    if getattr(view_cls, "_sentrix_official_language_bridge", False):
        return

    original_render = view_cls.render
    original_build_embed = view_cls.build_embed

    def render(self) -> None:
        original_render(self)
        # La langue reste transversale. Sur le Control Center V3 le menu principal occupe
        # déjà la première ligne ; le sélecteur de langue n'est ajouté à l'accueil que si
        # une ligne Discord reste disponible.
        if getattr(self, "category", None) is None:
            try:
                self.add_item(OfficialLanguageSelect(self))
            except ValueError:
                pass
        if _is_english(self):
            for item in self.children:
                _translate_component(item)

    async def build_embed(self):
        embed = await original_build_embed(self)
        if not _is_english(self):
            return embed
        embed.title = _english(embed.title)
        embed.description = _english(embed.description)
        for index, field in enumerate(list(embed.fields)):
            embed.set_field_at(
                index,
                name=_english(field.name) or field.name,
                value=_english(field.value) or field.value,
                inline=field.inline,
            )
        if embed.footer and embed.footer.text:
            embed.set_footer(
                text=_english(embed.footer.text),
                icon_url=embed.footer.icon_url or None,
            )
        return embed

    view_cls.render = render
    view_cls.build_embed = build_embed
    view_cls._sentrix_official_language_bridge = True
    view_cls._sentrix_native_language = True
    view_cls._sentrix_language_payload_guard = True
    logger.info("Langue FR/EN branchée sur le centre +setup.")


def _mark_official_help(bot: commands.Bot) -> None:
    command = bot.get_command("help")
    if command is None:
        return
    cog = getattr(command, "cog", None)
    if getattr(cog, "qualified_name", "") != "SentriXHelp":
        return
    command._sentrix_language_help = True
    command._sentrix_official_help = True
    app_command = getattr(command, "app_command", None)
    if app_command is not None:
        app_command._sentrix_language_help = True


async def install(bot: commands.Bot) -> None:
    _patch_setup()
    _mark_official_help(bot)

    # +help est volontairement chargé à la fin du runtime. C'est donc le point stable où
    # le Control Center V3 peut devenir la dernière autorité Setup, après permissions V3
    # et les anciens correctifs. On réapplique ensuite le pont FR/EN par-dessus V3.
    if bot.get_cog("SentriXHelp") is not None:
        from .control_center_v3 import install as install_control_center_v3
        await install_control_center_v3(bot)
        _patch_setup(force=True)

    bot._sentrix_official_language_bridge = True
