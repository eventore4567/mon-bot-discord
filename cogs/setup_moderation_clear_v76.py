"""SentriX V76 — page Modération utile et sans configuration de rôles.

Cette couche remplace l'ancien bloc « créer/préparer un rôle de modération » par des
réglages qui agissent réellement sur le comportement de la modération :
- activation/désactivation du module ;
- seuil de bannissement automatique après avertissements ;
- messages privés envoyés pour chaque type de sanction, avec texte par défaut,
  désactivation ou personnalisation.

Les permissions restent entièrement basées sur les permissions Discord réelles et la
hiérarchie des rôles. Aucun rôle de modération n'est créé ou modifié ici.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from utils import embeds
from utils import sentrix_panels as panels
from . import setup_experience_v74 as v74
from . import setup_control_center as setup_ui
from . import setup_v2_core as core

logger = logging.getLogger("bot.setup-moderation-useful-v76")
RUNTIME_MARKER = "Setup Moderation Useful V76"

DM_ACTIONS: tuple[tuple[str, str], ...] = (
    ("ban", "Bannissement"),
    ("tempban", "Bannissement temporaire"),
    ("kick", "Expulsion"),
    ("mute", "Mute / timeout"),
    ("warn", "Avertissement"),
    ("unban", "Débannissement"),
    ("unmute", "Retrait du mute"),
)

FALLBACK_DM_TEMPLATES = {
    "ban": "Vous avez été banni de {serveur}.\nRaison : {raison}",
    "tempban": "Vous avez été banni temporairement de {serveur} pendant {duree}.\nRaison : {raison}",
    "kick": "Vous avez été expulsé de {serveur}.\nRaison : {raison}",
    "mute": "Vous avez été rendu muet sur {serveur} pendant {duree}.\nRaison : {raison}",
    "warn": "Vous avez reçu un avertissement sur {serveur}.\nRaison : {raison}",
    "unban": "Votre bannissement de {serveur} a été retiré.\nRaison : {raison}",
    "unmute": "Votre mute sur {serveur} a été retiré.\nRaison : {raison}",
}


def _row_value(row, key: str, default=None):
    if row is None:
        return default
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return default if value is None else value


def _dm_label(action: str) -> str:
    return dict(DM_ACTIONS).get(action, action)


def _default_dm_template(view: v74.SentriXSetupV74, action: str) -> str:
    cog = view.bot.get_cog("Moderation")
    templates = getattr(cog, "DEFAULT_DM_TEMPLATES", None) if cog is not None else None
    if isinstance(templates, dict) and action in templates:
        return str(templates[action])
    return FALLBACK_DM_TEMPLATES[action]


async def _dm_settings(view: v74.SentriXSetupV74) -> dict[str, object]:
    rows = await view.bot.db.fetchall(
        "SELECT action, message, enabled FROM sanction_dm_templates WHERE guild_id = ?",
        (view.guild.id,),
    )
    return {str(_row_value(row, "action", "")): row for row in rows}


async def _set_dm_default(view: v74.SentriXSetupV74, action: str) -> None:
    await view.bot.db.execute(
        "DELETE FROM sanction_dm_templates WHERE guild_id = ? AND action = ?",
        (view.guild.id, action),
    )


async def _set_dm_disabled(view: v74.SentriXSetupV74, action: str) -> None:
    await view.bot.db.execute(
        """
        INSERT INTO sanction_dm_templates (guild_id, action, message, enabled)
        VALUES (?, ?, '', 0)
        ON CONFLICT(guild_id, action)
        DO UPDATE SET message = '', enabled = 0
        """,
        (view.guild.id, action),
    )


async def _set_dm_custom(view: v74.SentriXSetupV74, action: str, message: str) -> None:
    await view.bot.db.execute(
        """
        INSERT INTO sanction_dm_templates (guild_id, action, message, enabled)
        VALUES (?, ?, ?, 1)
        ON CONFLICT(guild_id, action)
        DO UPDATE SET message = excluded.message, enabled = 1
        """,
        (view.guild.id, action, message),
    )


async def _build_moderation_v76(self: v74.SentriXSetupV74) -> None:
    enabled = await core.module_enabled(self.bot, self.guild.id, "moderation")
    conf = await self.bot.db.get_guild_config(self.guild.id)
    try:
        warn_threshold = int(setup_ui._get(conf, "warn_ban_threshold") or 0)
    except (TypeError, ValueError):
        warn_threshold = 0

    dm_rows = await _dm_settings(self)
    active_dm_count = sum(
        1
        for action, _label in DM_ACTIONS
        if action not in dm_rows or bool(_row_value(dm_rows.get(action), "enabled", 1))
    )
    custom_dm_count = sum(
        1
        for action, _label in DM_ACTIONS
        if action in dm_rows and bool(_row_value(dm_rows.get(action), "enabled", 0))
    )

    status = discord.ui.Button(
        label="Activée" if enabled else "Désactivée",
        style=discord.ButtonStyle.success if enabled else discord.ButtonStyle.secondary,
        disabled=True,
    )

    container = discord.ui.Container(accent_colour=v74.v73.ACCENT)
    container.add_item(
        discord.ui.Section(
            discord.ui.TextDisplay(
                "# 🛡️ Modération\n"
                "Ici, **aucun rôle de modération n'est à créer ou à préparer**. SentriX utilise "
                "directement les permissions Discord de chaque membre et respecte la hiérarchie "
                "des rôles.\n\n"
                "Cette page sert uniquement à régler le **comportement des sanctions**."
            ),
            accessory=v74.v73._thumbnail(self.bot),
        )
    )
    container.add_item(discord.ui.Separator())

    threshold_text = (
        f"Ban automatique après **{warn_threshold} avertissements**"
        if warn_threshold > 0
        else "Ban automatique après avertissements : **désactivé**"
    )
    summary = (
        "### État actuel\n"
        f"{threshold_text}\n"
        f"MP de sanctions : **{active_dm_count}/{len(DM_ACTIONS)} actifs**"
        + (f" · **{custom_dm_count} personnalisés**" if custom_dm_count else "")
    )
    container.add_item(discord.ui.Section(discord.ui.TextDisplay(summary), accessory=status))

    toggle = discord.ui.Button(
        label="Désactiver la modération" if enabled else "Activer la modération",
        style=discord.ButtonStyle.danger if enabled else discord.ButtonStyle.success,
    )

    async def toggle_moderation(interaction: discord.Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer()
        await core.set_module_enabled(
            self.bot,
            self.guild.id,
            "moderation",
            not enabled,
            actor_id=interaction.user.id,
        )
        await self.refresh(interaction)

    toggle.callback = toggle_moderation
    container.add_item(discord.ui.ActionRow(toggle))
    container.add_item(discord.ui.Separator())

    container.add_item(
        discord.ui.TextDisplay(
            "### Bannissement automatique après avertissements\n"
            "Choisissez combien d'avertissements un membre peut recevoir avant que SentriX le "
            "bannisse automatiquement. **Désactivé** signifie qu'un warn ne déclenche jamais de ban."
        )
    )

    threshold_options = [
        discord.SelectOption(
            label="Désactivé",
            value="0",
            description="Les avertissements ne bannissent jamais automatiquement.",
            default=warn_threshold == 0,
        ),
        discord.SelectOption(
            label="2 avertissements",
            value="2",
            description="Ban automatique au deuxième avertissement.",
            default=warn_threshold == 2,
        ),
        discord.SelectOption(
            label="3 avertissements",
            value="3",
            description="Réglage recommandé pour la plupart des serveurs.",
            default=warn_threshold == 3,
        ),
        discord.SelectOption(
            label="4 avertissements",
            value="4",
            description="Tolérance plus élevée avant le bannissement.",
            default=warn_threshold == 4,
        ),
        discord.SelectOption(
            label="5 avertissements",
            value="5",
            description="Tolérance maximale proposée dans le Setup.",
            default=warn_threshold == 5,
        ),
    ]
    warn_select = discord.ui.Select(
        placeholder="Choisir le seuil d'avertissements",
        min_values=1,
        max_values=1,
        options=threshold_options,
    )

    async def set_warn_threshold(interaction: discord.Interaction):
        new_threshold = int(warn_select.values[0])
        if not interaction.response.is_done():
            await interaction.response.defer()
        await self.bot.db.set_guild_config(
            self.guild.id,
            "warn_ban_threshold",
            new_threshold,
        )
        await self.refresh(interaction)

    warn_select.callback = set_warn_threshold
    container.add_item(discord.ui.ActionRow(warn_select))
    container.add_item(discord.ui.Separator())

    container.add_item(
        discord.ui.TextDisplay(
            "### Messages privés envoyés lors des sanctions\n"
            "Choisissez une sanction, puis décidez si le membre reçoit le **message SentriX par "
            "défaut**, **aucun MP**, ou votre **propre texte**.\n"
            "Variables disponibles : `{membre}` `{serveur}` `{raison}` `{duree}` `{moderateur}` `{action}`"
        )
    )

    selected_action = getattr(self, "moderation_dm_action", "ban")
    if selected_action not in dict(DM_ACTIONS):
        selected_action = "ban"
        self.moderation_dm_action = selected_action

    action_select = discord.ui.Select(
        placeholder="Choisir la sanction à configurer",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(
                label=label,
                value=action,
                default=action == selected_action,
            )
            for action, label in DM_ACTIONS
        ],
    )

    async def choose_action(interaction: discord.Interaction):
        self.moderation_dm_action = action_select.values[0]
        if not interaction.response.is_done():
            await interaction.response.defer()
        await self.refresh(interaction)

    action_select.callback = choose_action
    container.add_item(discord.ui.ActionRow(action_select))

    row = dm_rows.get(selected_action)
    if row is None:
        dm_state = "Texte SentriX par défaut"
    elif not bool(_row_value(row, "enabled", 0)):
        dm_state = "MP désactivé"
    else:
        dm_state = "Texte personnalisé"

    state_button = discord.ui.Button(
        label=f"{_dm_label(selected_action)} : {dm_state}"[:80],
        style=(
            discord.ButtonStyle.danger
            if dm_state == "MP désactivé"
            else discord.ButtonStyle.success
        ),
        disabled=True,
    )
    container.add_item(discord.ui.ActionRow(state_button))

    use_default = discord.ui.Button(
        label="Texte par défaut",
        style=discord.ButtonStyle.secondary,
    )
    customize = discord.ui.Button(
        label="Personnaliser le MP",
        style=discord.ButtonStyle.primary,
    )
    disable_dm = discord.ui.Button(
        label="Désactiver le MP",
        style=discord.ButtonStyle.danger,
    )

    async def use_default_dm(interaction: discord.Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer()
        await _set_dm_default(self, selected_action)
        await self.refresh(interaction)

    async def disable_selected_dm(interaction: discord.Interaction):
        if not interaction.response.is_done():
            await interaction.response.defer()
        await _set_dm_disabled(self, selected_action)
        await self.refresh(interaction)

    async def customize_dm(interaction: discord.Interaction):
        current_row = dm_rows.get(selected_action)
        current_text = (
            str(_row_value(current_row, "message", ""))
            if current_row is not None and bool(_row_value(current_row, "enabled", 0))
            else _default_dm_template(self, selected_action)
        )
        action = selected_action
        label = _dm_label(action)

        class SanctionDMModal(discord.ui.Modal):
            def __init__(modal_self):
                super().__init__(title=f"MP — {label}"[:45])
                modal_self.message_input = discord.ui.TextInput(
                    label="Message envoyé au membre",
                    style=discord.TextStyle.paragraph,
                    default=current_text[:1900],
                    max_length=1900,
                    required=True,
                )
                modal_self.add_item(modal_self.message_input)

            async def on_submit(modal_self, modal_interaction: discord.Interaction):
                text = str(modal_self.message_input.value).strip()
                if not text:
                    return await panels.envoyer(modal_interaction.response, panels.depuis_embed(embeds.error('Le message ne peut pas être vide.')), ephemere=True)
                await _set_dm_custom(self, action, text)
                await panels.envoyer(modal_interaction.response, panels.depuis_embed(embeds.success(f'Le MP de **{label}** est maintenant personnalisé. Le nouveau texte sera utilisé dès la prochaine sanction.')), ephemere=True)

        await interaction.response.send_modal(SanctionDMModal())

    use_default.callback = use_default_dm
    customize.callback = customize_dm
    disable_dm.callback = disable_selected_dm
    container.add_item(discord.ui.ActionRow(use_default, customize, disable_dm))

    self._add_navigation(container)
    self.add_item(container)


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_setup_moderation_useful_v76", False):
        return

    cls = v74.SentriXSetupV74
    current = cls._build_moderation
    if not getattr(current, "_sentrix_moderation_useful_v76", False):
        _build_moderation_v76._sentrix_moderation_useful_v76 = True
        _build_moderation_v76._sentrix_previous = current
        cls._build_moderation = _build_moderation_v76

    v74.CATEGORY_META["moderation"] = (
        "🛡️",
        "Modération",
        "Sanctions, avertissements automatiques et messages privés — sans rôle à configurer.",
    )

    bot._sentrix_setup_moderation_useful_v76 = True
    logger.info(
        "%s installé : rôle builder supprimé, seuil de warns et MP de sanctions ajoutés.",
        RUNTIME_MARKER,
    )


__all__ = ["install"]
