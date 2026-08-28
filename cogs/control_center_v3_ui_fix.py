"""Finition déterministe de l'interface du Control Center V3/V4.

Cette couche est volontairement la dernière autorité visuelle du Setup officiel :
- un seul contrôle compact Activer/Désactiver par module ;
- un seul état du module dans l'embed ;
- suppression des anciennes lignes télémétriques Etat/Configuration/Module ;
- restauration des contrôles dynamiques Tickets et Notifications ;
- informations Tickets utiles directement dans la page.

Le nettoyage s'applique après ``render`` ET après ``build_embed`` afin qu'une couche
historique chargée plus tôt ne puisse pas réinjecter le gros bouton bleu observé en
production.
"""
from __future__ import annotations

import logging
import re
import unicodedata

import discord
from discord.ext import commands

from . import setup_control_center as setup_ui

logger = logging.getLogger("bot.control-center-v3-ui-fix")

_LEGACY_TOGGLE_LABELS = {
    "activer / desactiver le module",
    "activer/desactiver le module",
    "activer ou desactiver le module",
    "enable / disable module",
    "enable/disable module",
    "enable or disable module",
}
_COMPACT_TOGGLE_LABELS = {"activer", "desactiver", "enable", "disable"}
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
_CONFIG_FIELD_NAMES = {
    "configuration",
    "configuration actuelle",
    "current configuration",
}
_STATUS_WORDS = {"actif", "inactif", "active", "inactive", "on", "off"}


def _plain(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(char for char in text if not unicodedata.combining(char)).strip()


def _looks_like_legacy_module_toggle(child: discord.ui.Item) -> bool:
    if not isinstance(child, discord.ui.Button):
        return False
    label = _plain(getattr(child, "label", ""))
    if label in _LEGACY_TOGGLE_LABELS:
        return True
    # Les anciennes versions n'ont pas toutes exactement le même libellé. On retire
    # donc sémantiquement tout bouton qui promet à la fois activer ET désactiver le module.
    french = "module" in label and "activer" in label and "desactiver" in label
    english = "module" in label and "enable" in label and "disable" in label
    return french or english


def _normalize_module_toggles(view: discord.ui.View) -> int:
    """Garantit un seul toggle principal et privilégie le bouton compact V3."""
    removed = 0
    compact: list[discord.ui.Button] = []
    for child in list(view.children):
        if not isinstance(child, discord.ui.Button):
            continue
        if _looks_like_legacy_module_toggle(child):
            view.remove_item(child)
            removed += 1
            continue
        if _plain(getattr(child, "label", "")) in _COMPACT_TOGGLE_LABELS:
            compact.append(child)

    # Sur une page module, plusieurs petits toggles identiques sont aussi un bug.
    if getattr(view, "category", None) is not None and len(compact) > 1:
        for duplicate in compact[1:]:
            view.remove_item(duplicate)
            removed += 1
    return removed


def _remove_dynamic_components(view: discord.ui.View) -> None:
    for child in list(view.children):
        if isinstance(child, _DYNAMIC_COMPONENTS):
            view.remove_item(child)


async def _restore_dynamic_components(view) -> None:
    """Rejoue seulement la préparation asynchrone utile aux pages qui en dépendent."""
    if getattr(view, "category", None) not in {"tickets", "notifications"}:
        return
    _remove_dynamic_components(view)
    await view.prepare()


def _strip_status_telemetry(embed: discord.Embed) -> None:
    """Supprime l'ancienne ligne `Etat • Configuration • Module` de la description."""
    description = str(embed.description or "")
    if not description:
        return

    kept: list[str] = []
    for line in description.splitlines():
        normalized = _plain(re.sub(r"[*_`]+", "", line))
        has_state = "etat" in normalized or "state" in normalized
        has_config = "configuration" in normalized or "config" in normalized
        has_module = "module" in normalized
        has_status = any(word in normalized.split() for word in _STATUS_WORDS)
        telemetry_separator = "•" in line or " | " in line
        if has_state and has_config and has_module and has_status and telemetry_separator:
            continue
        kept.append(line)

    cleaned = "\n".join(kept).strip()
    embed.description = cleaned or None


def _tidy_module_header(embed: discord.Embed) -> discord.Embed:
    """Conserve un seul état et empêche Etat/Config/Module de se répéter."""
    fields = list(embed.fields)
    state_value = None
    state_indices: list[int] = []
    english = False

    for index, field in enumerate(fields):
        key = _plain(field.name)
        if key in {"state", "module state"}:
            english = True
        if key in _STATE_FIELD_NAMES:
            value = str(field.value or "").strip()
            # Le champ `Module` représente l'état réel du toggle et a priorité sur
            # l'ancien champ `Etat` qui pouvait être CONFIGURE/ERREUR.
            if key in {"module", "module state", "etat du module"} and value:
                state_value = value
            elif state_value is None and value:
                state_value = value
            state_indices.append(index)

    for index in reversed(state_indices):
        embed.remove_field(index)

    if state_value is not None:
        embed.insert_field_at(
            0,
            name="Module state" if english else "État du module",
            value=state_value,
            inline=False,
        )

    # Une configuration courte reste sur sa propre ligne : elle ne fusionne plus avec
    # l'état et les permissions sur mobile.
    config_seen = False
    for index in reversed(range(len(embed.fields))):
        field = embed.fields[index]
        if _plain(field.name) not in _CONFIG_FIELD_NAMES:
            continue
        if config_seen:
            embed.remove_field(index)
            continue
        embed.set_field_at(
            index,
            name="Current configuration" if english else "Configuration actuelle",
            value=field.value,
            inline=False,
        )
        config_seen = True

    # Permissions toujours sur une ligne complète.
    for index, field in enumerate(list(embed.fields)):
        key = _plain(field.name)
        if key in {"permissions", "permissions du bot", "bot permissions"}:
            embed.set_field_at(index, name=field.name, value=field.value, inline=False)
    return embed


def _channel(guild: discord.Guild, channel_id, *, english: bool) -> str:
    if not channel_id:
        return "Not configured" if english else "Non configuré"
    channel = guild.get_channel(int(channel_id))
    return channel.mention if channel else ("Missing" if english else "Introuvable")


def _role(guild: discord.Guild, role_id, *, english: bool) -> str:
    if not role_id:
        return "Not configured" if english else "Non configuré"
    role = guild.get_role(int(role_id))
    return role.mention if role else ("Missing" if english else "Introuvable")


def _drop_fields(embed: discord.Embed, names: set[str]) -> None:
    for index in reversed(range(len(embed.fields))):
        if _plain(embed.fields[index].name) in names:
            embed.remove_field(index)


async def _enrich_ticket_page(view, embed: discord.Embed) -> None:
    if getattr(view, "category", None) != "tickets":
        return

    english = any(
        _plain(field.name) in {"state", "module state", "current configuration"}
        for field in embed.fields
    )
    panels = await view.bot.db.fetchall(
        "SELECT id,name,channel_id,enabled FROM ticket_panels_v2 WHERE guild_id=? ORDER BY id",
        (view.guild.id,),
    )
    types = await view.bot.db.fetchall(
        "SELECT id,name,staff_role_id,category_id,log_channel_id FROM ticket_types WHERE guild_id=? ORDER BY id",
        (view.guild.id,),
    )

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
        state = (
            ("ACTIVE" if enabled else "INACTIVE")
            if english
            else ("ACTIF" if enabled else "INACTIF")
        )
        panel_lines.append(
            f"**{setup_ui._get(row, 'name', 'Panel')}** - {state} - "
            f"{_channel(view.guild, setup_ui._get(row, 'channel_id'), english=english)}"
        )

    type_lines = []
    for row in types[:12]:
        support = _role(view.guild, setup_ui._get(row, "staff_role_id"), english=english)
        category = _channel(view.guild, setup_ui._get(row, "category_id"), english=english)
        if english:
            type_lines.append(
                f"**{setup_ui._get(row, 'name', 'Ticket')}** - Support: {support} - Category: {category}"
            )
        else:
            type_lines.append(
                f"**{setup_ui._get(row, 'name', 'Ticket')}** - Support : {support} - Catégorie : {category}"
            )

    embed.add_field(
        name="Configured panels" if english else "Panels configurés",
        value=(
            "\n".join(panel_lines)[:1024]
            if panel_lines
            else ("No panel configured." if english else "Aucun panel configuré.")
        ),
        inline=False,
    )
    embed.add_field(
        name="Ticket types" if english else "Types de tickets",
        value=(
            "\n".join(type_lines)[:1024]
            if type_lines
            else ("No ticket type configured." if english else "Aucun type de ticket configuré.")
        ),
        inline=False,
    )

    selected_id = getattr(view, "selected_ticket", None)
    if selected_id:
        selected = next(
            (
                row for row in types
                if int(setup_ui._get(row, "id", 0) or 0) == int(selected_id)
            ),
            None,
        )
        if selected is not None:
            support = _role(view.guild, setup_ui._get(selected, "staff_role_id"), english=english)
            category = _channel(view.guild, setup_ui._get(selected, "category_id"), english=english)
            logs = _channel(view.guild, setup_ui._get(selected, "log_channel_id"), english=english)
            if english:
                detail = f"**Support:** {support}\n**Category:** {category}\n**Logs:** {logs}"
            else:
                detail = f"**Support :** {support}\n**Catégorie :** {category}\n**Logs :** {logs}"
            embed.add_field(
                name="Selected ticket type" if english else "Type sélectionné",
                value=detail,
                inline=False,
            )


def install(bot: commands.Bot) -> None:
    """Pose/répare la finition sur les méthodes actuellement finales du Setup."""
    view_cls = setup_ui.SetupView

    current_render = view_cls.render
    if not getattr(current_render, "_sentrix_control_center_v3_ui_fix_render", False):
        def render(self, *args, **kwargs):
            result = current_render(self, *args, **kwargs)
            _normalize_module_toggles(self)
            return result

        render._sentrix_control_center_v3_ui_fix_render = True
        render._sentrix_original = current_render
        view_cls.render = render

    current_build = view_cls.build_embed
    if not getattr(current_build, "_sentrix_control_center_v3_ui_fix_build", False):
        async def build_embed(self):
            embed = await current_build(self)

            _normalize_module_toggles(self)
            await _restore_dynamic_components(self)
            _normalize_module_toggles(self)

            _strip_status_telemetry(embed)
            _tidy_module_header(embed)
            await _enrich_ticket_page(self, embed)
            return embed

        build_embed._sentrix_control_center_v3_ui_fix_build = True
        build_embed._sentrix_original = current_build
        view_cls.build_embed = build_embed

    bot._sentrix_control_center_v3_ui_fix = True
    logger.info(
        "Finition Setup active : 1 état, 1 toggle compact, télémétrie legacy retirée, Tickets/Notifications restaurés."
    )


__all__ = ["install"]
