"""Finition deterministe de l'interface du Control Center V3.

Cette couche corrige uniquement la composition Discord finale du Setup officiel :
- un seul controle Activer/Desactiver par module ;
- un seul etat de module dans l'embed ;
- restauration des controles dynamiques Tickets et Notifications que le renderer V3
  remplace sinon avant l'appel historique a ``SetupView.prepare`` ;
- informations Tickets utiles directement dans la page, sans renvoyer vers une ancienne
  commande de configuration.

Elle s'applique apres les ponts de langue afin de nettoyer aussi les composants injectes
par les couches de compatibilite historiques.
"""
from __future__ import annotations

import logging
import unicodedata

import discord
from discord.ext import commands

from . import setup_control_center as setup_ui

logger = logging.getLogger("bot.control-center-v3-ui-fix")

_LEGACY_TOGGLE_LABELS = {
    "activer / desactiver le module",
    "activer/desactiver le module",
    "enable / disable module",
    "enable/disable module",
}

_DYNAMIC_COMPONENTS = (
    setup_ui.TicketSelect,
    setup_ui.TicketCategorySelect,
    setup_ui.TicketRoleSelect,
    setup_ui.NotificationSelect,
    setup_ui.NotificationChannelSelect,
    setup_ui.NotificationRoleSelect,
)

_STATE_FIELD_NAMES = {
    "etat",
    "etat du module",
    "module",
    "state",
    "module state",
}
_CONFIG_FIELD_NAMES = {"configuration", "configuration actuelle", "current configuration"}


def _plain(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(char for char in text if not unicodedata.combining(char)).strip()


def _remove_legacy_module_toggle(view: discord.ui.View) -> int:
    """Retire l'ancien gros bouton bleu sans toucher au petit ModuleToggle V3."""
    removed = 0
    for child in list(view.children):
        if not isinstance(child, discord.ui.Button):
            continue
        label = _plain(getattr(child, "label", ""))
        if label not in _LEGACY_TOGGLE_LABELS:
            continue
        view.remove_item(child)
        removed += 1
    return removed


def _remove_dynamic_components(view: discord.ui.View) -> None:
    for child in list(view.children):
        if isinstance(child, _DYNAMIC_COMPONENTS):
            view.remove_item(child)


async def _restore_dynamic_components(view) -> None:
    """Rejoue seulement la preparation asynchrone utile aux pages qui en dependent."""
    if getattr(view, "category", None) not in {"tickets", "notifications"}:
        return
    _remove_dynamic_components(view)
    await view.prepare()


def _tidy_module_header(embed: discord.Embed) -> discord.Embed:
    """Conserve un seul etat et empeche le trio Etat/Config/Module de se tasser."""
    fields = list(embed.fields)
    if not fields:
        return embed

    state_value = None
    state_indices: list[int] = []
    english = False

    for index, field in enumerate(fields):
        key = _plain(field.name)
        if key in {"state", "module state"}:
            english = True
        if key in _STATE_FIELD_NAMES:
            if state_value is None and str(field.value or "").strip():
                state_value = str(field.value)
            state_indices.append(index)

    for index in reversed(state_indices):
        embed.remove_field(index)

    if state_value is not None:
        embed.insert_field_at(
            0,
            name="Module state" if english else "Etat du module",
            value=state_value,
            inline=False,
        )

    # Une configuration courte reste sur sa propre ligne : sur mobile elle ne fusionne
    # plus avec l'etat et les permissions.
    for index, field in enumerate(list(embed.fields)):
        if _plain(field.name) not in _CONFIG_FIELD_NAMES:
            continue
        embed.set_field_at(
            index,
            name="Current configuration" if english else "Configuration actuelle",
            value=field.value,
            inline=False,
        )
        break

    return embed


def _channel(guild: discord.Guild, channel_id, *, english: bool) -> str:
    if not channel_id:
        return "Not configured" if english else "Non configure"
    channel = guild.get_channel(int(channel_id))
    return channel.mention if channel else ("Missing" if english else "Introuvable")


def _role(guild: discord.Guild, role_id, *, english: bool) -> str:
    if not role_id:
        return "Not configured" if english else "Non configure"
    role = guild.get_role(int(role_id))
    return role.mention if role else ("Missing" if english else "Introuvable")


def _drop_fields(embed: discord.Embed, names: set[str]) -> None:
    for index in reversed(range(len(embed.fields))):
        if _plain(embed.fields[index].name) in names:
            embed.remove_field(index)


async def _enrich_ticket_page(view, embed: discord.Embed) -> None:
    if getattr(view, "category", None) != "tickets":
        return

    english = any(_plain(field.name) in {"state", "module state", "current configuration"} for field in embed.fields)
    panels = await view.bot.db.fetchall(
        "SELECT id,name,channel_id,enabled FROM ticket_panels_v2 WHERE guild_id=? ORDER BY id",
        (view.guild.id,),
    )
    types = await view.bot.db.fetchall(
        "SELECT id,name,staff_role_id,category_id,log_channel_id FROM ticket_types WHERE guild_id=? ORDER BY id",
        (view.guild.id,),
    )

    # Le wrapper peut etre rappele plusieurs fois pendant un refresh : aucune duplication.
    _drop_fields(
        embed,
        {
            "panels configures", "configured panels",
            "types de tickets", "ticket types",
            "type selectionne", "selected ticket type",
        },
    )

    panel_lines = []
    for row in panels[:10]:
        enabled = bool(setup_ui._get(row, "enabled", 1))
        state = ("ACTIVE" if enabled else "INACTIVE") if english else ("ACTIF" if enabled else "INACTIF")
        panel_lines.append(
            f"**{setup_ui._get(row, 'name', 'Panel')}** - {state} - "
            f"{_channel(view.guild, setup_ui._get(row, 'channel_id'), english=english)}"
        )

    type_lines = []
    for row in types[:12]:
        support = _role(view.guild, setup_ui._get(row, "staff_role_id"), english=english)
        category = _channel(view.guild, setup_ui._get(row, "category_id"), english=english)
        if english:
            type_lines.append(f"**{setup_ui._get(row, 'name', 'Ticket')}** - Support: {support} - Category: {category}")
        else:
            type_lines.append(f"**{setup_ui._get(row, 'name', 'Ticket')}** - Support : {support} - Categorie : {category}")

    embed.add_field(
        name="Configured panels" if english else "Panels configures",
        value=("\n".join(panel_lines)[:1024] if panel_lines else ("No panel configured." if english else "Aucun panel configure.")),
        inline=False,
    )
    embed.add_field(
        name="Ticket types" if english else "Types de tickets",
        value=("\n".join(type_lines)[:1024] if type_lines else ("No ticket type configured." if english else "Aucun type de ticket configure.")),
        inline=False,
    )

    selected_id = getattr(view, "selected_ticket", None)
    if selected_id:
        selected = next((row for row in types if int(setup_ui._get(row, "id", 0) or 0) == int(selected_id)), None)
        if selected is not None:
            support = _role(view.guild, setup_ui._get(selected, "staff_role_id"), english=english)
            category = _channel(view.guild, setup_ui._get(selected, "category_id"), english=english)
            logs = _channel(view.guild, setup_ui._get(selected, "log_channel_id"), english=english)
            if english:
                detail = f"**Support:** {support}\n**Category:** {category}\n**Logs:** {logs}"
            else:
                detail = f"**Support :** {support}\n**Categorie :** {category}\n**Logs :** {logs}"
            embed.add_field(
                name="Selected ticket type" if english else "Type selectionne",
                value=detail,
                inline=False,
            )


def install(bot: commands.Bot) -> None:
    """Pose la finition sur les methodes actuellement finales du Setup officiel."""
    view_cls = setup_ui.SetupView
    current_build = view_cls.build_embed
    if getattr(current_build, "_sentrix_control_center_v3_ui_fix", False):
        _remove_marker = getattr(bot, "_sentrix_control_center_v3_ui_fix", False)
        if not _remove_marker:
            bot._sentrix_control_center_v3_ui_fix = True
        return

    async def build_embed(self):
        embed = await current_build(self)

        # Les anciennes couches peuvent injecter le gros toggle soit dans render(), soit
        # pendant build/prepare(). On nettoie avant ET apres la preparation dynamique.
        _remove_legacy_module_toggle(self)
        await _restore_dynamic_components(self)
        _remove_legacy_module_toggle(self)

        _tidy_module_header(embed)
        await _enrich_ticket_page(self, embed)
        return embed

    build_embed._sentrix_control_center_v3_ui_fix = True
    build_embed._sentrix_original = current_build
    view_cls.build_embed = build_embed
    bot._sentrix_control_center_v3_ui_fix = True
    logger.info(
        "Finition Control Center V3 active : toggle unique, entete aeree et controles Tickets/Notifications restaures."
    )


__all__ = ["install"]
