"""SentriX V72 — états propres et activation Tickets réellement fonctionnelle.

V72 est une couche finale, volontairement ciblée :
- corrige l'affichage des ConfigState internes sur l'accueil V70 ;
- calcule un état effectif qui tient compte du vrai switch de module ;
- remplace le toggle Tickets par un bouton capable de configurer/réparer le système ;
- crée seulement les ressources manquantes et conserve les réglages existants ;
- empêche les anciens panels d'ouvrir un ticket lorsque le module Tickets est coupé.

Aucune permission Discord n'est accordée à un membre par le Setup. Quand aucun rôle de
support n'existe, SentriX crée un rôle Support vide qu'un administrateur peut attribuer.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import discord
from discord.ext import commands

from utils import embeds
from . import control_center_v3
from . import setup_control_center as setup_ui
from . import setup_polish_v70 as v70
from . import setup_v2_core as core
from . import tickets as ticket_runtime

logger = logging.getLogger("bot.setup-ticket-autoconfig-v72")

RUNTIME_MARKER = "Control Center V72"
_PANEL_TOPIC = "sentrix-ticket-panel:v72"
_LOG_TOPIC = "sentrix-ticket-logs:v72"
_LOCKS: dict[int, asyncio.Lock] = {}


class TicketBootstrapError(RuntimeError):
    pass


def _lock(guild_id: int) -> asyncio.Lock:
    current = _LOCKS.get(int(guild_id))
    if current is None:
        current = asyncio.Lock()
        _LOCKS[int(guild_id)] = current
    return current


def _row_get(row: Any, key: str, default=None):
    if row is None:
        return default
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        value = getattr(row, key, default)
    return default if value is None else value


def state_text(value: object) -> str:
    """Transforme ConfigState/texte en état utilisateur, jamais en repr Python."""
    raw_value = getattr(value, "value", value)
    raw = str(raw_value or "").strip().upper().replace("CONFIGSTATE.", "")
    normalized = raw.replace("_", " ")

    if raw in {"ERROR", "ERREUR"} or any(word in normalized for word in ("CORRIGER", "MANQUANT")):
        return "! À CORRIGER"
    if raw in {"UNCONFIGURED", "NON CONFIGURE", "NON CONFIGURÉ"} or "NON CONFIG" in normalized:
        return "— NON CONFIGURÉ"
    if raw in {"INACTIVE", "INACTIF", "OFF", "0"}:
        return "○ INACTIF"
    if raw in {"ACTIVE", "ACTIF", "ON", "1"}:
        return "● ACTIF"
    return "— NON CONFIGURÉ"


def _footer(panel: discord.Embed, *, page: str | None = None) -> discord.Embed:
    suffix = f" • {v70._label(page)}" if page else ""
    panel.set_footer(text=f"SentriX • Control Center V72{suffix} • Sauvegarde automatique")
    return panel


async def _effective_states(view) -> tuple[dict[str, str], dict[str, tuple]]:
    conf = await view.bot.db.get_guild_config(view.guild.id)
    statuses = await setup_ui.module_statuses(view.bot, view.guild, conf)
    result: dict[str, str] = {}

    for key, data in statuses.items():
        state = data[0]
        if state == setup_ui.ConfigState.ERROR:
            result[key] = "! À CORRIGER"
            continue

        module_enabled = await core.module_enabled(view.bot, view.guild.id, key)
        if not module_enabled:
            result[key] = "○ INACTIF"
            continue

        # Un module sans vraie configuration ne doit pas apparaître ACTIF uniquement
        # parce que module_settings vaut 1 par défaut.
        result[key] = state_text(state)

    permissions_enabled = await core.module_enabled(view.bot, view.guild.id, "permissions")
    result["permissions"] = "● ACTIF" if permissions_enabled else "○ INACTIF"
    return result, statuses


async def _home(view) -> discord.Embed:
    effective, statuses = await _effective_states(view)

    # Tickets peut être "module ON" tout en restant inutilisable si aucun panel/type n'a
    # été créé. Dans ce cas on l'indique clairement comme à configurer.
    if await core.module_enabled(view.bot, view.guild.id, "tickets"):
        ready = await ticket_configuration_ready(view.bot, view.guild)
        if not ready and effective.get("tickets") != "! À CORRIGER":
            effective["tickets"] = "— À CONFIGURER"

    active = sum(value == "● ACTIF" for value in effective.values())
    errors = sum(value == "! À CORRIGER" for value in effective.values())
    completion = setup_ui._completion(statuses)

    panel = v70._panel(
        "SentriX — Control Center",
        f"**{completion}% configuré**  ·  **{active}/{len(effective)} modules actifs**  ·  **{errors} à corriger**",
        context=view.guild.name,
    )

    groups = (
        ("ESSENTIEL", ("moderation", "security", "logs")),
        ("COMMUNAUTÉ", ("tickets", "welcome", "roles")),
        ("SERVICES", ("levels", "notifications", "ai", "permissions")),
    )
    for heading, keys in groups:
        lines: list[str] = []
        for key in keys:
            if key not in effective:
                continue
            lines.append(f"**{v70._label(key)}**\n{effective[key]}")
        if lines:
            panel.add_field(name=heading, value="\n".join(lines), inline=True)

    problems: list[str] = []
    for key, data in statuses.items():
        if data[0] != setup_ui.ConfigState.ERROR:
            continue
        detail = data[2][0] if data[2] else "Configuration à vérifier."
        problems.append(f"**{v70._label(key)}** — {detail}")
    if problems:
        panel.add_field(name="À CORRIGER", value="\n".join(problems)[:1024], inline=False)

    panel.add_field(
        name="NAVIGATION",
        value=(
            "Choisissez une page dans le menu ci-dessous. "
            "Sur **Tickets**, le bouton Activer / Désactiver crée automatiquement la configuration manquante."
        ),
        inline=False,
    )
    return _footer(panel)


def _text_channel(guild: discord.Guild, channel_id: Any) -> discord.TextChannel | None:
    try:
        channel = guild.get_channel(int(channel_id)) if channel_id else None
    except (TypeError, ValueError):
        return None
    return channel if isinstance(channel, discord.TextChannel) else None


def _category(guild: discord.Guild, channel_id: Any) -> discord.CategoryChannel | None:
    try:
        channel = guild.get_channel(int(channel_id)) if channel_id else None
    except (TypeError, ValueError):
        return None
    return channel if isinstance(channel, discord.CategoryChannel) else None


def _role(guild: discord.Guild, role_id: Any) -> discord.Role | None:
    try:
        role = guild.get_role(int(role_id)) if role_id else None
    except (TypeError, ValueError):
        return None
    if role is None or role.is_default() or role.managed:
        return None
    return role


def _channel_by_topic(guild: discord.Guild, marker: str) -> discord.TextChannel | None:
    for channel in guild.text_channels:
        if marker in str(channel.topic or ""):
            return channel
    return None


def _named_role(guild: discord.Guild, name: str) -> discord.Role | None:
    folded = name.casefold()
    for role in guild.roles:
        if not role.is_default() and not role.managed and role.name.casefold() == folded:
            return role
    return None


async def _existing_ticket_rows(bot: commands.Bot, guild_id: int):
    panels = await bot.db.fetchall(
        "SELECT * FROM ticket_panels_v2 WHERE guild_id=? ORDER BY enabled DESC,id",
        (guild_id,),
    )
    panel = panels[0] if panels else None
    types = (
        await bot.db.fetchall(
            "SELECT * FROM ticket_types WHERE panel_id=? ORDER BY position,id",
            (_row_get(panel, "id"),),
        )
        if panel is not None
        else []
    )
    return panels, panel, types


async def ticket_configuration_ready(bot: commands.Bot, guild: discord.Guild) -> bool:
    panels, panel, types = await _existing_ticket_rows(bot, guild.id)
    if panel is None or not types or not bool(_row_get(panel, "enabled", 1)):
        return False
    panel_channel = _text_channel(guild, _row_get(panel, "channel_id"))
    if panel_channel is None:
        return False
    first = types[0]
    return bool(
        _role(guild, _row_get(first, "staff_role_id"))
        and _category(guild, _row_get(first, "category_id"))
        and _text_channel(guild, _row_get(first, "log_channel_id"))
    )


async def _ensure_support_role(guild: discord.Guild, conf, types: list) -> tuple[discord.Role, bool]:
    for ticket_type in types:
        role = _role(guild, _row_get(ticket_type, "staff_role_id"))
        if role is not None:
            return role, False

    role = _role(guild, setup_ui._get(conf, "mod_role"))
    if role is not None:
        return role, False

    role = _named_role(guild, "Support")
    if role is not None:
        return role, False

    me = guild.me
    if me is None or not me.guild_permissions.manage_roles:
        raise TicketBootstrapError(
            "Aucun rôle support n'est configuré et SentriX n'a pas la permission **Gérer les rôles**."
        )
    created = await guild.create_role(
        name="Support",
        permissions=discord.Permissions.none(),
        mentionable=False,
        reason="SentriX V72 : configuration automatique des tickets",
    )
    return created, True


async def _ensure_category(
    guild: discord.Guild,
    conf,
    panel,
    types: list,
    support_role: discord.Role,
) -> tuple[discord.CategoryChannel, bool]:
    for ticket_type in types:
        category = _category(guild, _row_get(ticket_type, "category_id"))
        if category is not None:
            return category, False

    category = _category(guild, setup_ui._get(conf, "ticket_category"))
    if category is not None:
        return category, False

    panel_channel = _text_channel(guild, _row_get(panel, "channel_id")) if panel else None
    if panel_channel and isinstance(panel_channel.category, discord.CategoryChannel):
        return panel_channel.category, False

    marker_channel = _channel_by_topic(guild, _PANEL_TOPIC)
    if marker_channel and isinstance(marker_channel.category, discord.CategoryChannel):
        return marker_channel.category, False

    me = guild.me
    if me is None or not me.guild_permissions.manage_channels:
        raise TicketBootstrapError("SentriX a besoin de **Gérer les salons** pour créer la catégorie Tickets.")

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        support_role: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
        ),
        me: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            manage_channels=True,
            manage_permissions=True,
            read_message_history=True,
        ),
    }
    category = await guild.create_category(
        "Tickets",
        overwrites=overwrites,
        reason="SentriX V72 : configuration automatique des tickets",
    )
    return category, True


async def _ensure_panel_channel(
    guild: discord.Guild,
    panel,
    category: discord.CategoryChannel,
    support_role: discord.Role,
) -> tuple[discord.TextChannel, bool]:
    channel = _text_channel(guild, _row_get(panel, "channel_id")) if panel else None
    if channel is not None:
        return channel, False

    channel = _channel_by_topic(guild, _PANEL_TOPIC)
    if channel is not None:
        return channel, False

    me = guild.me
    if me is None or not me.guild_permissions.manage_channels:
        raise TicketBootstrapError("SentriX a besoin de **Gérer les salons** pour créer le salon d'ouverture.")

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=False,
            read_message_history=True,
        ),
        support_role: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
        ),
        me: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            manage_messages=True,
            read_message_history=True,
        ),
    }
    channel = await guild.create_text_channel(
        "ouvrir-un-ticket",
        category=category,
        topic=f"{_PANEL_TOPIC} • Panel public SentriX",
        overwrites=overwrites,
        reason="SentriX V72 : configuration automatique des tickets",
    )
    return channel, True


async def _ensure_log_channel(
    guild: discord.Guild,
    conf,
    types: list,
    category: discord.CategoryChannel,
    support_role: discord.Role,
) -> tuple[discord.TextChannel, bool]:
    for ticket_type in types:
        channel = _text_channel(guild, _row_get(ticket_type, "log_channel_id"))
        if channel is not None:
            return channel, False

    channel = _text_channel(guild, setup_ui._get(conf, "ticket_log_channel"))
    if channel is not None:
        return channel, False

    channel = _channel_by_topic(guild, _LOG_TOPIC)
    if channel is not None:
        return channel, False

    me = guild.me
    if me is None or not me.guild_permissions.manage_channels:
        raise TicketBootstrapError("SentriX a besoin de **Gérer les salons** pour créer les logs Tickets.")

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        support_role: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
        ),
        me: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            manage_messages=True,
            read_message_history=True,
        ),
    }
    channel = await guild.create_text_channel(
        "ticket-logs",
        category=category,
        topic=f"{_LOG_TOPIC} • Journaux privés SentriX",
        overwrites=overwrites,
        reason="SentriX V72 : configuration automatique des tickets",
    )
    return channel, True


async def _publish_panel(
    bot: commands.Bot,
    cog: ticket_runtime.Tickets,
    guild: discord.Guild,
    panel_id: int,
    channel: discord.TextChannel,
) -> discord.Message:
    panel = await cog.get_panel(panel_id)
    types = await cog.get_panel_types(panel_id)
    if panel is None or not types:
        raise TicketBootstrapError("Le panel ou son type Support n'a pas pu être créé.")

    view = ticket_runtime.TicketPanelView(panel, types)
    message = None
    old_id = _row_get(panel, "message_id")
    if old_id:
        try:
            message = await channel.fetch_message(int(old_id))
            await message.edit(embed=cog.build_panel_embed(panel), view=view)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            message = None

    if message is None:
        message = await channel.send(embed=cog.build_panel_embed(panel), view=view)

    await bot.db.execute(
        "UPDATE ticket_panels_v2 SET message_id=?,channel_id=?,enabled=1 WHERE id=?",
        (message.id, channel.id, panel_id),
    )
    try:
        bot.add_view(view, message_id=message.id)
    except (ValueError, discord.HTTPException):
        # La vue envoyée fonctionne déjà pendant ce processus ; restore_panel_views la
        # réenregistrera au prochain redémarrage.
        pass
    return message


async def ensure_ticket_configuration(
    bot: commands.Bot,
    guild: discord.Guild,
    *,
    actor_id: int,
) -> dict[str, Any]:
    """Crée/répare le minimum utilisable sans écraser les choix déjà configurés."""
    async with _lock(guild.id):
        cog = bot.get_cog("Tickets")
        if not isinstance(cog, ticket_runtime.Tickets):
            raise TicketBootstrapError("Le moteur Tickets n'est pas chargé.")

        conf = await bot.db.get_guild_config(guild.id)
        panels, panel, types = await _existing_ticket_rows(bot, guild.id)

        created_discord: list[Any] = []
        created_panel_id: int | None = None
        created_type_id: int | None = None
        try:
            support_role, made = await _ensure_support_role(guild, conf, types)
            if made:
                created_discord.append(support_role)

            category, made = await _ensure_category(guild, conf, panel, types, support_role)
            if made:
                created_discord.append(category)

            panel_channel, made = await _ensure_panel_channel(guild, panel, category, support_role)
            if made:
                created_discord.append(panel_channel)

            log_channel, made = await _ensure_log_channel(guild, conf, types, category, support_role)
            if made:
                created_discord.append(log_channel)

            if panel is None:
                created_panel_id = await cog.create_panel(guild.id, "Support")
                panel_id = created_panel_id
            else:
                panel_id = int(_row_get(panel, "id"))

            current_types = await cog.get_panel_types(panel_id)
            if current_types:
                ticket_type = current_types[0]
                type_id = int(_row_get(ticket_type, "id"))
            else:
                created_type_id = await cog.add_type(guild.id, panel_id, "Support")
                type_id = created_type_id

            await bot.db.execute(
                "UPDATE ticket_panels_v2 SET channel_id=?,enabled=1 WHERE id=?",
                (panel_channel.id, panel_id),
            )
            # COALESCE préserve un réglage personnalisé déjà présent.
            await bot.db.execute(
                "UPDATE ticket_types SET "
                "staff_role_id=COALESCE(staff_role_id,?),"
                "category_id=COALESCE(category_id,?),"
                "log_channel_id=COALESCE(log_channel_id,?) "
                "WHERE id=?",
                (support_role.id, category.id, log_channel.id, type_id),
            )

            await bot.db.set_guild_config(guild.id, "ticket_category", category.id)
            await bot.db.set_guild_config(guild.id, "ticket_log_channel", log_channel.id)
            message = await _publish_panel(bot, cog, guild, panel_id, panel_channel)

            await core.set_module_enabled(
                bot,
                guild.id,
                "tickets",
                True,
                actor_id=actor_id,
            )
            return {
                "role": support_role,
                "category": category,
                "panel_channel": panel_channel,
                "log_channel": log_channel,
                "panel_id": panel_id,
                "type_id": type_id,
                "message": message,
            }
        except Exception:
            # Nettoyage uniquement de ce que V72 vient de créer. Les ressources/configs
            # utilisateur déjà présentes ne sont jamais supprimées par un échec automatique.
            if created_type_id is not None:
                try:
                    await bot.db.execute("DELETE FROM ticket_types WHERE id=?", (created_type_id,))
                except Exception:
                    pass
            if created_panel_id is not None:
                try:
                    await bot.db.execute("DELETE FROM ticket_panels_v2 WHERE id=?", (created_panel_id,))
                except Exception:
                    pass
            for resource in reversed(created_discord):
                try:
                    await resource.delete(reason="Rollback SentriX V72 : configuration Tickets incomplète")
                except (discord.Forbidden, discord.HTTPException):
                    pass
            raise


async def _ack(interaction: discord.Interaction) -> None:
    if interaction.response.is_done():
        return
    try:
        await interaction.response.defer()
    except discord.InteractionResponded:
        pass


class TicketModuleButton(discord.ui.Button):
    def __init__(self, owner):
        self.owner = owner
        super().__init__(
            label="Activer / Désactiver",
            style=discord.ButtonStyle.primary,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        await _ack(interaction)
        enabled = await core.module_enabled(self.owner.bot, self.owner.guild.id, "tickets")
        ready = await ticket_configuration_ready(self.owner.bot, self.owner.guild)

        if enabled and ready:
            await core.set_module_enabled(
                self.owner.bot,
                self.owner.guild.id,
                "tickets",
                False,
                actor_id=interaction.user.id,
            )
            await self.owner.audit(interaction.user.id, "module:tickets", "off")
            await self.owner.refresh(interaction)
            return await interaction.followup.send(
                embed=embeds.warning(
                    "Le module **Tickets** est désactivé. La configuration est conservée et pourra être réactivée sans recréer les salons."
                ),
                ephemeral=True,
            )

        try:
            result = await ensure_ticket_configuration(
                self.owner.bot,
                self.owner.guild,
                actor_id=interaction.user.id,
            )
        except TicketBootstrapError as exc:
            return await interaction.followup.send(embed=embeds.error(str(exc)), ephemeral=True)
        except (discord.Forbidden, discord.HTTPException) as exc:
            logger.exception("Discord a refusé la configuration automatique Tickets V72.")
            return await interaction.followup.send(
                embed=embeds.error(
                    "Discord a refusé une étape de la configuration automatique. Vérifiez **Gérer les salons**, **Gérer les rôles**, **Voir les salons** et **Envoyer des messages** pour SentriX."
                ),
                ephemeral=True,
            )
        except Exception:
            logger.exception("Configuration automatique Tickets V72 impossible.")
            return await interaction.followup.send(
                embed=embeds.error("La configuration automatique des tickets a rencontré une erreur technique."),
                ephemeral=True,
            )

        await self.owner.audit(interaction.user.id, "module:tickets", "on+autoconfig")
        await self.owner.refresh(interaction)
        return await interaction.followup.send(
            embed=embeds.success(
                "**Tickets configurés et activés.**\n"
                f"Panel : {result['panel_channel'].mention}\n"
                f"Catégorie : **{result['category'].name}**\n"
                f"Rôle support : {result['role'].mention}\n"
                f"Logs : {result['log_channel'].mention}"
            ),
            ephemeral=True,
        )


def _install_setup_render() -> None:
    cls = setup_ui.SetupView
    current = cls.render
    if getattr(current, "_sentrix_setup_ticket_v72", False):
        return

    def render_v72(self) -> None:
        current(self)
        if getattr(self, "category", None) != "tickets":
            return
        for child in list(self.children):
            if isinstance(child, TicketModuleButton):
                self.remove_item(child)
                continue
            if isinstance(child, control_center_v3.ModuleToggle) and getattr(child, "module", None) == "tickets":
                self.remove_item(child)
        try:
            self.add_item(TicketModuleButton(self))
        except ValueError:
            logger.exception("Impossible d'ajouter le toggle Tickets V72 au Setup.")

    render_v72._sentrix_setup_ticket_v72 = True
    render_v72._sentrix_previous = current
    cls.render = render_v72


def _install_ticket_runtime_guard() -> None:
    current = ticket_runtime.Tickets.start_ticket_flow
    if getattr(current, "_sentrix_ticket_module_guard_v72", False):
        return

    async def start_ticket_flow_v72(self, interaction: discord.Interaction, type_id: int):
        guild = interaction.guild
        if guild is not None and not await core.module_enabled(self.bot, guild.id, "tickets"):
            panel = embeds.warning("Le système de tickets est actuellement désactivé sur ce serveur.")
            if interaction.response.is_done():
                return await interaction.followup.send(embed=panel, ephemeral=True)
            return await interaction.response.send_message(embed=panel, ephemeral=True)
        return await current(self, interaction, type_id)

    start_ticket_flow_v72._sentrix_ticket_module_guard_v72 = True
    start_ticket_flow_v72._sentrix_previous = current
    ticket_runtime.Tickets.start_ticket_flow = start_ticket_flow_v72


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_setup_ticket_autoconfig_v72", False):
        return

    # Les fonctions V70 résolvent ces symboles globalement au moment du rendu. Les
    # remplacer ici corrige toutes les nouvelles vues sans empiler un autre build_embed.
    v70._state = state_text
    v70._home = _home
    v70._footer = _footer

    _install_setup_render()
    _install_ticket_runtime_guard()

    bot._sentrix_setup_ticket_autoconfig_v72 = True
    logger.info(
        "Setup V72 actif : états ConfigState nettoyés, Tickets auto-configurables et panels bloqués quand le module est OFF."
    )


async def setup(bot: commands.Bot) -> None:
    install(bot)


__all__ = [
    "install",
    "state_text",
    "ticket_configuration_ready",
    "ensure_ticket_configuration",
    "TicketModuleButton",
]
