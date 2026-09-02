"""SentriX V72 — états propres et activation Tickets réellement fonctionnelle.

V72 reste une finition ciblée au-dessus de V70/V71 :
- aucune valeur interne ``ConfigState.*`` n'est visible ;
- l'accueil distingue module coupé, non configuré, actif et à corriger ;
- le bouton Tickets crée/répare une vraie configuration exploitable ;
- les réglages existants sont réutilisés et jamais écrasés volontairement ;
- les panels déjà publiés respectent réellement le switch ON/OFF du module.
"""
from __future__ import annotations

import asyncio
import importlib
import logging
from typing import Any

import discord
from discord.ext import commands

from utils import embeds
from utils import sentrix_panels as panels
from . import control_center_v3
from . import setup_control_center as setup_ui
from . import setup_polish_v70 as v70
from . import setup_v2_core as core

logger = logging.getLogger("bot.setup-ticket-autoconfig-v72")

RUNTIME_MARKER = "Control Center V72"
_PANEL_TOPIC = "sentrix-ticket-panel:v72"
_LOG_TOPIC = "sentrix-ticket-logs:v72"
_LOCKS: dict[int, asyncio.Lock] = {}


class TicketBootstrapError(RuntimeError):
    pass


def _tickets_module():
    """Retourne le module Tickets réellement chargé par discord.py.

    ``cogs.__init__`` est exécuté avant ``bot.load_extension('cogs.tickets')``. Importer
    Tickets au niveau module ici conserverait donc une ancienne classe si discord.py
    réexécute ensuite l'extension. La résolution tardive garantit que V72 patche et utilise
    toujours le Cog réellement enregistré dans le bot.
    """
    return importlib.import_module(f"{__package__}.tickets")


def _lock(guild_id: int) -> asyncio.Lock:
    lock = _LOCKS.get(int(guild_id))
    if lock is None:
        lock = asyncio.Lock()
        _LOCKS[int(guild_id)] = lock
    return lock


def _row_get(row: Any, key: str, default=None):
    if row is None:
        return default
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        value = getattr(row, key, default)
    return default if value is None else value


def state_text(value: object) -> str:
    """Convertit Enum/texte en état utilisateur sans exposer l'objet Python."""
    raw_value = getattr(value, "value", value)
    raw = str(raw_value or "").strip().upper().replace("CONFIGSTATE.", "")
    normalized = raw.replace("_", " ")

    if (
        raw == "ERROR"
        or raw.startswith("ERREUR")
        or "CORRIGER" in normalized
        or "MANQUANT" in normalized
    ):
        return "! À CORRIGER"
    if raw == "UNCONFIGURED" or "NON CONFIG" in normalized:
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
    effective: dict[str, str] = {}

    for key, data in statuses.items():
        state = data[0]
        if state == setup_ui.ConfigState.ERROR:
            effective[key] = "! À CORRIGER"
            continue
        if not await core.module_enabled(view.bot, view.guild.id, key):
            effective[key] = "○ INACTIF"
            continue
        effective[key] = state_text(state)

    permissions_enabled = await core.module_enabled(view.bot, view.guild.id, "permissions")
    effective["permissions"] = "● ACTIF" if permissions_enabled else "○ INACTIF"
    return effective, statuses


async def _home(view) -> discord.Embed:
    effective, statuses = await _effective_states(view)

    if await core.module_enabled(view.bot, view.guild.id, "tickets"):
        if not await ticket_configuration_ready(view.bot, view.guild):
            if effective.get("tickets") != "! À CORRIGER":
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
        lines = [
            f"**{v70._label(key)}**\n{effective[key]}"
            for key in keys
            if key in effective
        ]
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
            "Choisissez une page dans le menu ci-dessous. Sur **Tickets**, "
            "le bouton Activer / Désactiver crée automatiquement ce qui manque."
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
    return next(
        (channel for channel in guild.text_channels if marker in str(channel.topic or "")),
        None,
    )


def _named_support_role(guild: discord.Guild) -> discord.Role | None:
    accepted = {"support", "staff", "modérateur", "moderateur"}
    return next(
        (
            role for role in reversed(guild.roles)
            if not role.is_default()
            and not role.managed
            and role.name.casefold() in accepted
        ),
        None,
    )


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
    _panels, panel, types = await _existing_ticket_rows(bot, guild.id)
    if panel is None or not types or not bool(_row_get(panel, "enabled", 1)):
        return False
    if _text_channel(guild, _row_get(panel, "channel_id")) is None:
        return False
    return all(
        _role(guild, _row_get(ticket_type, "staff_role_id"))
        and _category(guild, _row_get(ticket_type, "category_id"))
        and _text_channel(guild, _row_get(ticket_type, "log_channel_id"))
        for ticket_type in types
    )


async def _ensure_support_role(guild: discord.Guild, conf, types: list) -> tuple[discord.Role, bool]:
    for ticket_type in types:
        role = _role(guild, _row_get(ticket_type, "staff_role_id"))
        if role is not None:
            return role, False

    role = _role(guild, setup_ui._get(conf, "mod_role")) or _named_support_role(guild)
    if role is not None:
        return role, False

    me = guild.me
    if me is None or not me.guild_permissions.manage_roles:
        raise TicketBootstrapError(
            "Aucun rôle support n'est disponible et SentriX n'a pas **Gérer les rôles**."
        )
    role = await guild.create_role(
        name="Support",
        permissions=discord.Permissions.none(),
        mentionable=False,
        reason="SentriX V72 : configuration automatique des tickets",
    )
    return role, True


def _private_overwrites(
    guild: discord.Guild,
    support_role: discord.Role,
) -> dict[Any, discord.PermissionOverwrite]:
    me = guild.me
    if me is None:
        raise TicketBootstrapError("SentriX est introuvable dans la liste des membres du serveur.")
    return {
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
            manage_roles=True,
            read_message_history=True,
        ),
    }


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

    marker = _channel_by_topic(guild, _PANEL_TOPIC)
    if marker and isinstance(marker.category, discord.CategoryChannel):
        return marker.category, False

    me = guild.me
    if me is None or not me.guild_permissions.manage_channels:
        raise TicketBootstrapError("SentriX a besoin de **Gérer les salons** pour créer la catégorie Tickets.")
    category = await guild.create_category(
        "Tickets",
        overwrites=_private_overwrites(guild, support_role),
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

    overwrites = _private_overwrites(guild, support_role)
    overwrites[guild.default_role] = discord.PermissionOverwrite(
        view_channel=True,
        send_messages=False,
        read_message_history=True,
    )
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
    channel = await guild.create_text_channel(
        "ticket-logs",
        category=category,
        topic=f"{_LOG_TOPIC} • Journaux privés SentriX",
        overwrites=_private_overwrites(guild, support_role),
        reason="SentriX V72 : configuration automatique des tickets",
    )
    return channel, True


async def _publish_panel(
    bot: commands.Bot,
    cog: Any,
    panel_id: int,
    channel: discord.TextChannel,
) -> discord.Message:
    ticket_runtime = _tickets_module()
    panel = await cog.get_panel(panel_id)
    types = await cog.get_panel_types(panel_id)
    if panel is None or not types:
        raise TicketBootstrapError("Le panel ou son type Support n'a pas pu être créé.")

    view = ticket_runtime.TicketPanelView(panel, types)
    message = None
    old_message_id = _row_get(panel, "message_id")
    if old_message_id:
        try:
            message = await channel.fetch_message(int(old_message_id))
            await message.edit(embed=cog.build_panel_embed(panel), view=view)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            message = None
    if message is None:
        message = await channel.send(embed=cog.build_panel_embed(panel), view=view)

    await bot.db.execute(
        "UPDATE ticket_panels_v2 SET message_id=?,channel_id=?,enabled=1 WHERE id=?",
        (message.id, channel.id, panel_id),
    )
    return message


async def ensure_ticket_configuration(
    bot: commands.Bot,
    guild: discord.Guild,
    *,
    actor_id: int,
) -> dict[str, Any]:
    """Crée/répare le minimum utilisable, puis active Tickets seulement à la fin."""
    async with _lock(guild.id):
        cog = bot.get_cog("Tickets")
        required = ("create_panel", "add_type", "get_panel", "get_panel_types", "build_panel_embed")
        if cog is None or not all(callable(getattr(cog, name, None)) for name in required):
            raise TicketBootstrapError("Le moteur Tickets n'est pas chargé.")

        conf = await bot.db.get_guild_config(guild.id)
        _panels, panel, types = await _existing_ticket_rows(bot, guild.id)
        created_resources: list[Any] = []
        created_panel_id: int | None = None
        created_type_id: int | None = None

        try:
            support_role, made = await _ensure_support_role(guild, conf, types)
            if made:
                created_resources.append(support_role)

            category, made = await _ensure_category(guild, conf, panel, types, support_role)
            if made:
                created_resources.append(category)

            panel_channel, made = await _ensure_panel_channel(guild, panel, category, support_role)
            if made:
                created_resources.append(panel_channel)

            log_channel, made = await _ensure_log_channel(guild, conf, types, category, support_role)
            if made:
                created_resources.append(log_channel)

            if panel is None:
                created_panel_id = await cog.create_panel(guild.id, "Support")
                panel_id = created_panel_id
            else:
                panel_id = int(_row_get(panel, "id"))

            current_types = await cog.get_panel_types(panel_id)
            if not current_types:
                created_type_id = await cog.add_type(guild.id, panel_id, "Support")
                current_types = await cog.get_panel_types(panel_id)
            if not current_types:
                raise TicketBootstrapError("Le type Support n'a pas pu être créé.")

            await bot.db.execute(
                "UPDATE ticket_panels_v2 SET channel_id=?,enabled=1 WHERE id=?",
                (panel_channel.id, panel_id),
            )
            await bot.db.execute(
                "UPDATE ticket_types SET "
                "staff_role_id=COALESCE(staff_role_id,?),"
                "category_id=COALESCE(category_id,?),"
                "log_channel_id=COALESCE(log_channel_id,?) "
                "WHERE panel_id=?",
                (support_role.id, category.id, log_channel.id, panel_id),
            )

            await bot.db.set_guild_config(guild.id, "ticket_category", category.id)
            await bot.db.set_guild_config(guild.id, "ticket_log_channel", log_channel.id)
            message = await _publish_panel(bot, cog, panel_id, panel_channel)

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
                "message": message,
            }
        except Exception:
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
            for resource in reversed(created_resources):
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
            return await panels.envoyer(interaction.followup, panels.depuis_embed(embeds.warning('Le module **Tickets** est désactivé. La configuration est conservée et pourra être réactivée sans recréer les salons.')), ephemere=True)

        try:
            result = await ensure_ticket_configuration(
                self.owner.bot,
                self.owner.guild,
                actor_id=interaction.user.id,
            )
        except TicketBootstrapError as exc:
            return await panels.envoyer(interaction.followup, panels.depuis_embed(embeds.error(str(exc))), ephemere=True)
        except (discord.Forbidden, discord.HTTPException):
            logger.exception("Discord a refusé la configuration automatique Tickets V72.")
            return await panels.envoyer(interaction.followup, panels.depuis_embed(embeds.error('Discord a refusé une étape. Vérifiez **Gérer les salons**, **Gérer les rôles**, **Voir les salons** et **Envoyer des messages** pour SentriX.')), ephemere=True)
        except Exception:
            logger.exception("Configuration automatique Tickets V72 impossible.")
            return await panels.envoyer(interaction.followup, panels.depuis_embed(embeds.error('La configuration automatique des tickets a rencontré une erreur technique.')), ephemere=True)

        await self.owner.audit(interaction.user.id, "module:tickets", "on+autoconfig")
        await self.owner.refresh(interaction)
        return await panels.envoyer(interaction.followup, panels.depuis_embed(embeds.success(f"**Tickets configurés et activés.**\nPanel : {result['panel_channel'].mention}\nCatégorie : **{result['category'].name}**\nRôle support : {result['role'].mention}\nLogs : {result['log_channel'].mention}")), ephemere=True)


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
            elif (
                isinstance(child, control_center_v3.ModuleToggle)
                and getattr(child, "module", None) == "tickets"
            ):
                self.remove_item(child)
        try:
            self.add_item(TicketModuleButton(self))
        except ValueError:
            logger.exception("Impossible d'ajouter le toggle Tickets V72 au Setup.")

    render_v72._sentrix_setup_ticket_v72 = True
    render_v72._sentrix_previous = current
    cls.render = render_v72


def _install_ticket_runtime_guard() -> None:
    ticket_runtime = _tickets_module()
    current = ticket_runtime.Tickets.start_ticket_flow
    if getattr(current, "_sentrix_ticket_module_guard_v72", False):
        return

    async def start_ticket_flow_v72(self, interaction: discord.Interaction, type_id: int):
        guild = interaction.guild
        if guild is not None and not await core.module_enabled(self.bot, guild.id, "tickets"):
            panel = embeds.warning("Le système de tickets est actuellement désactivé sur ce serveur.")
            if interaction.response.is_done():
                return await panels.envoyer(interaction.followup, panels.depuis_embed(panel), ephemere=True)
            return await panels.envoyer(interaction.response, panels.depuis_embed(panel), ephemere=True)
        return await current(self, interaction, type_id)

    start_ticket_flow_v72._sentrix_ticket_module_guard_v72 = True
    start_ticket_flow_v72._sentrix_previous = current
    ticket_runtime.Tickets.start_ticket_flow = start_ticket_flow_v72


def install(bot: commands.Bot) -> None:
    if getattr(bot, "_sentrix_setup_ticket_autoconfig_v72", False):
        return

    v70._state = state_text
    v70._home = _home
    v70._footer = _footer
    _install_setup_render()
    _install_ticket_runtime_guard()

    bot._sentrix_setup_ticket_autoconfig_v72 = True
    logger.info(
        "Setup V72 actif : états propres, Tickets auto-configurables et panels bloqués quand le module est OFF."
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
