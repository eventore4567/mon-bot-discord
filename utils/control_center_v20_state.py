"""Lecture, validation et rendu des états de configuration SentriX V20."""
from __future__ import annotations

from collections import OrderedDict

import discord
from discord.ext import commands

from utils import embeds, log_service
from utils.control_center_v20_meta import (
    BAR, HELP_CATEGORY_ORDER, LOG_TYPES_SHOWN, SECURITY_FIELDS, SETUP_CATEGORIES,
    STATE_ACTIVE, STATE_ERROR, STATE_INACTIVE, STATE_UNCONFIGURED, ModuleSnapshot,
    _all_help_commands, _bot_missing_permissions, _command_description, _command_usage,
    _help_category, _human_permission, _permission_from_checks, _row_get, _slash_map,
    _state_for_resource,
)


async def _snapshot(bot: commands.Bot, guild: discord.Guild, key: str) -> ModuleSnapshot:
    meta = SETUP_CATEGORIES[key]
    missing = _bot_missing_permissions(guild, meta["bot_permissions"])
    conf = await bot.db.get_guild_config(guild.id)

    if key == "moderation":
        staff_state, staff = _state_for_resource(guild, _row_get(conf, "mod_role"), "role")
        warn_state, warn_role = _state_for_resource(guild, _row_get(conf, "warn_role"), "role")
        dm_row = await bot.db.fetchone(
            "SELECT COUNT(*) AS n FROM sanction_dm_templates WHERE guild_id = ?", (guild.id,)
        )
        threshold = int(_row_get(conf, "warn_ban_threshold", 3) or 0)
        state = STATE_ERROR if STATE_ERROR in {staff_state, warn_state} else STATE_ACTIVE
        lines = [
            f"Rôle staff : {staff}",
            f"Rôle avertissement : {warn_role}",
            f"Ban automatique : {'désactivé' if threshold == 0 else f'{threshold} warn(s)'}",
            f"Messages privés de sanction : {int(_row_get(dm_row, 'n', 0))} personnalisé(s)",
            "Permissions staff : permissions Discord exactes",
        ]
        return ModuleSnapshot(
            key, state, lines, missing,
            "Un rôle configuré n’existe plus." if state == STATE_ERROR else None,
        )

    if key == "security":
        row = await bot.db.get_automod(guild.id)
        if row is None:
            return ModuleSnapshot(
                key, STATE_UNCONFIGURED,
                [f"{label} : {STATE_UNCONFIGURED}" for label in SECURITY_FIELDS.values()],
                missing,
            )
        enabled_count = 0
        lines = []
        for field_name, label in SECURITY_FIELDS.items():
            enabled = bool(_row_get(row, field_name, 0))
            enabled_count += int(enabled)
            lines.append(f"{label} : {STATE_ACTIVE if enabled else STATE_INACTIVE}")
        return ModuleSnapshot(
            key, STATE_ACTIVE if enabled_count else STATE_INACTIVE, lines, missing
        )

    if key == "logs":
        settings = await log_service.get_all_log_settings(bot, guild.id)
        lines, broken, configured, enabled_count = [], False, False, 0
        for log_type, label in LOG_TYPES_SHOWN.items():
            setting = settings.get(log_type, {})
            enabled = bool(setting.get("enabled"))
            channel_id = setting.get("channel_id")
            configured = configured or bool(channel_id)
            enabled_count += int(enabled)
            if enabled:
                ok, _reason = log_service.validate_channel(
                    guild, channel_id, needs_file=(log_type == "tickets")
                )
                if not ok:
                    broken = True
                    state = STATE_ERROR
                else:
                    state = STATE_ACTIVE
            else:
                state = STATE_INACTIVE if channel_id else STATE_UNCONFIGURED
            lines.append(f"{label} : {state}")
        state = (
            STATE_ERROR if broken else STATE_ACTIVE if enabled_count
            else STATE_INACTIVE if configured else STATE_UNCONFIGURED
        )
        return ModuleSnapshot(
            key, state, lines, missing,
            "Au moins un salon de logs configuré est supprimé ou inutilisable."
            if broken else None,
        )

    if key == "tickets":
        panels = await bot.db.fetchall(
            "SELECT * FROM ticket_panels_v2 WHERE guild_id = ? ORDER BY id", (guild.id,)
        )
        types = await bot.db.fetchall(
            "SELECT * FROM ticket_types WHERE guild_id = ? ORDER BY id", (guild.id,)
        )
        if not panels:
            return ModuleSnapshot(
                key, STATE_UNCONFIGURED,
                [
                    "Panel : Non configuré",
                    "Types : 0",
                    f"Transcript DM : {STATE_ACTIVE if bool(_row_get(conf, 'ticket_transcript_dm', 1)) else STATE_INACTIVE}",
                ],
                missing,
            )
        broken_reasons = []
        active_panels = 0
        for panel in panels:
            if bool(_row_get(panel, "enabled", 1)):
                active_panels += 1
                channel_id = _row_get(panel, "channel_id")
                if channel_id and guild.get_channel(int(channel_id)) is None:
                    broken_reasons.append("salon du panel supprimé")
        for ticket_type in types:
            role_id = _row_get(ticket_type, "staff_role_id")
            category_id = _row_get(ticket_type, "category_id")
            if role_id and guild.get_role(int(role_id)) is None:
                broken_reasons.append("rôle support supprimé")
            if category_id and guild.get_channel(int(category_id)) is None:
                broken_reasons.append("catégorie ticket supprimée")
        state = STATE_ERROR if broken_reasons else STATE_ACTIVE if active_panels else STATE_INACTIVE
        support_roles = len({
            int(_row_get(ticket_type, "staff_role_id"))
            for ticket_type in types if _row_get(ticket_type, "staff_role_id")
        })
        lines = [
            f"Panels : {len(panels)} ({active_panels} actif(s))",
            f"Types de tickets : {len(types)}",
            f"Rôles support : {support_roles}",
            f"Transcript DM : {STATE_ACTIVE if bool(_row_get(conf, 'ticket_transcript_dm', 1)) else STATE_INACTIVE}",
        ]
        return ModuleSnapshot(
            key, state, lines, missing,
            ", ".join(dict.fromkeys(broken_reasons)) if broken_reasons else None,
        )

    if key == "welcome":
        welcome_state, welcome = _state_for_resource(
            guild, _row_get(conf, "welcome_channel"), "channel"
        )
        goodbye_state, goodbye = _state_for_resource(
            guild, _row_get(conf, "goodbye_channel"), "channel"
        )
        role_state, autorole = _state_for_resource(
            guild, _row_get(conf, "autorole"), "role"
        )
        states = {welcome_state, goodbye_state, role_state}
        if STATE_ERROR in states:
            state = STATE_ERROR
        elif welcome_state == STATE_ACTIVE or goodbye_state == STATE_ACTIVE:
            state = STATE_ACTIVE
        else:
            state = STATE_UNCONFIGURED
        lines = [
            f"Bienvenue : {welcome}",
            f"Départ : {goodbye}",
            f"Autorole : {autorole}",
            f"Message bienvenue : {'personnalisé' if _row_get(conf, 'welcome_message') else 'par défaut'}",
            f"Image bienvenue : {'configurée' if _row_get(conf, 'welcome_image_url') else 'aucune'}",
        ]
        return ModuleSnapshot(
            key, state, lines, missing,
            "Un salon ou rôle configuré n’existe plus." if state == STATE_ERROR else None,
        )

    if key == "roles":
        columns = [
            ("autorole", "Autorole"),
            ("member_role", "Rôle membre"),
            ("verify_role", "Vérification"),
            ("booster_role", "Booster"),
            ("mute_role", "Mute"),
        ]
        states, lines = [], []
        for column, label in columns:
            state, value = _state_for_resource(guild, _row_get(conf, column), "role")
            states.append(state)
            lines.append(f"{label} : {value}")
        state = (
            STATE_ERROR if STATE_ERROR in states else
            STATE_ACTIVE if STATE_ACTIVE in states else STATE_UNCONFIGURED
        )
        return ModuleSnapshot(
            key, state, lines, missing,
            "Un rôle configuré a été supprimé." if state == STATE_ERROR else None,
        )

    if key == "levels_economy":
        channel_state, level_channel = _state_for_resource(
            guild, _row_get(conf, "level_channel"), "channel"
        )
        shop_row = await bot.db.fetchone(
            "SELECT COUNT(*) AS n FROM shop_items WHERE guild_id = ?", (guild.id,)
        )
        level_roles = await bot.db.fetchone(
            "SELECT COUNT(*) AS n FROM level_roles WHERE guild_id = ?", (guild.id,)
        )
        state = STATE_ERROR if channel_state == STATE_ERROR else STATE_ACTIVE
        lines = [
            f"Niveaux / XP : {STATE_ACTIVE}",
            f"Économie / banque : {STATE_ACTIVE}",
            f"Salon level-up : {level_channel}",
            f"Récompenses de niveau : {int(_row_get(level_roles, 'n', 0))}",
            f"Articles boutique : {int(_row_get(shop_row, 'n', 0))}",
            "Conservation membre : niveau, XP, messages, argent, banque et statistiques préservés",
        ]
        return ModuleSnapshot(
            key, state, lines, missing,
            "Le salon level-up configuré a été supprimé." if state == STATE_ERROR else None,
        )

    if key == "notifications":
        rows = await bot.db.fetchall(
            "SELECT * FROM social_notifications WHERE guild_id = ? ORDER BY id", (guild.id,)
        )
        if not rows:
            return ModuleSnapshot(
                key, STATE_UNCONFIGURED,
                ["YouTube : Non configuré", "Twitch : Non configuré", "TikTok : Non configuré"],
                missing,
            )
        broken = False
        platforms: dict[str, list[str]] = {"youtube": [], "twitch": [], "tiktok": []}
        active = 0
        for row in rows:
            enabled = bool(_row_get(row, "enabled", 1))
            active += int(enabled)
            channel_id = _row_get(row, "discord_channel_id")
            role_id = _row_get(row, "role_id")
            if channel_id and guild.get_channel(int(channel_id)) is None:
                broken = True
            if role_id and guild.get_role(int(role_id)) is None:
                broken = True
            platform = str(_row_get(row, "platform", "autre") or "autre").casefold()
            platforms.setdefault(platform, []).append(STATE_ACTIVE if enabled else STATE_INACTIVE)
        lines = []
        for platform in ("youtube", "twitch", "tiktok"):
            values = platforms.get(platform, [])
            lines.append(f"{platform.title()} : {', '.join(values) if values else STATE_UNCONFIGURED}")
        state = STATE_ERROR if broken else STATE_ACTIVE if active else STATE_INACTIVE
        return ModuleSnapshot(
            key, state, lines, missing,
            "Un salon ou rôle de notification configuré n’existe plus." if broken else None,
        )

    if key == "ai":
        row = await bot.db.fetchone("SELECT * FROM ai_settings WHERE guild_id = ?", (guild.id,))
        if row is None:
            return ModuleSnapshot(
                key, STATE_ACTIVE,
                [
                    "Assistant : ACTIF (valeurs par défaut)",
                    "Génération d’images : disponible",
                    "Accès : membres",
                    "Limites : valeurs par défaut",
                ],
                missing,
            )
        enabled = bool(_row_get(row, "enabled", 1))
        roles = str(_row_get(row, "allowed_role_ids", "[]"))
        channels = str(_row_get(row, "allowed_channel_ids", "[]"))
        lines = [
            f"Assistant : {STATE_ACTIVE if enabled else STATE_INACTIVE}",
            "Génération d’images : disponible",
            f"Cooldown : {int(_row_get(row, 'cooldown_seconds', 0))} s",
            f"Limite / minute : {int(_row_get(row, 'per_minute_limit', 0))}",
            f"Limite / jour : {int(_row_get(row, 'daily_limit', 0))}",
            f"Restrictions rôles : {'aucune' if roles in {'[]', ''} else 'configurées'}",
            f"Restrictions salons : {'aucune' if channels in {'[]', ''} else 'configurées'}",
        ]
        return ModuleSnapshot(key, STATE_ACTIVE if enabled else STATE_INACTIVE, lines, missing)

    return ModuleSnapshot(key, STATE_UNCONFIGURED, [], missing)


def _apply_permission_health(snapshot: ModuleSnapshot) -> ModuleSnapshot:
    if snapshot.state == STATE_ACTIVE and snapshot.missing_permissions:
        snapshot.state = STATE_ERROR
        snapshot.problem = snapshot.problem or (
            "SentriX n’a pas toutes les permissions Discord nécessaires pour ce module."
        )
    return snapshot


async def _all_snapshots(bot: commands.Bot, guild: discord.Guild) -> OrderedDict[str, ModuleSnapshot]:
    result: OrderedDict[str, ModuleSnapshot] = OrderedDict()
    for key in SETUP_CATEGORIES:
        try:
            result[key] = _apply_permission_health(await _snapshot(bot, guild, key))
        except Exception as exc:
            result[key] = ModuleSnapshot(
                key, STATE_ERROR, ["Lecture impossible"],
                _bot_missing_permissions(guild, SETUP_CATEGORIES[key]["bot_permissions"]),
                type(exc).__name__,
            )
    return result


def _setup_embed(title: str, description: str) -> discord.Embed:
    panel = discord.Embed(
        title=title,
        description=f"{BAR}\n{description}",
        colour=discord.Colour(embeds.COLOR_BRAND_UI),
    )
    panel.set_footer(text="SentriX • Configuration")
    return panel


async def _home_embed(bot: commands.Bot, guild: discord.Guild) -> discord.Embed:
    snapshots = await _all_snapshots(bot, guild)
    completed = sum(1 for snapshot in snapshots.values() if snapshot.complete)
    active = sum(1 for snapshot in snapshots.values() if snapshot.state == STATE_ACTIVE)
    percent = round(completed / max(1, len(snapshots)) * 100)
    panel = _setup_embed(
        "SentriX — Configuration",
        "Configurez les fonctionnalités de SentriX pour ce serveur.",
    )
    panel.add_field(name="Serveur", value=guild.name, inline=True)
    panel.add_field(name="Modules actifs", value=f"{active} / {len(snapshots)}", inline=True)
    panel.add_field(name="Configuration", value=f"{percent} % terminée", inline=True)
    for key, meta in SETUP_CATEGORIES.items():
        snapshot = snapshots[key]
        value = snapshot.state
        if snapshot.problem:
            value += f"\n{snapshot.problem[:130]}"
        panel.add_field(name=meta["title"], value=value, inline=True)
    return panel


async def _category_embed(bot: commands.Bot, guild: discord.Guild, key: str) -> discord.Embed:
    meta = SETUP_CATEGORIES[key]
    snapshot = _apply_permission_health(await _snapshot(bot, guild, key))
    panel = _setup_embed(f"SentriX — {meta['title']}", meta["description"])
    panel.add_field(name="État", value=snapshot.state, inline=False)
    panel.add_field(
        name="Configuration",
        value="\n\n".join(snapshot.lines)[:1024] or "Aucune information.",
        inline=False,
    )
    permission_lines = []
    for permission in meta["bot_permissions"]:
        label = _human_permission(permission)
        permission_lines.append(
            f"{label} : {'MANQUANT' if label in snapshot.missing_permissions else 'OK'}"
        )
    panel.add_field(
        name="Permissions SentriX",
        value="\n".join(permission_lines) or "Aucune permission supplémentaire.",
        inline=False,
    )
    if snapshot.problem:
        panel.add_field(name="À corriger", value=snapshot.problem[:1024], inline=False)
    return panel


def _help_home_embed(bot: commands.Bot) -> discord.Embed:
    commands_all = _all_help_commands(bot)
    grouped = {category: [] for category in HELP_CATEGORY_ORDER}
    for command in commands_all:
        grouped.setdefault(_help_category(command), []).append(command)
    panel = _setup_embed(
        "SentriX — Centre d’aide",
        "Retrouvez rapidement les commandes et fonctionnalités de SentriX.",
    )
    for category in HELP_CATEGORY_ORDER:
        rows = grouped.get(category, [])
        if not rows:
            continue
        preview = ", ".join(command.name for command in rows[:6])
        if len(rows) > 6:
            preview += "…"
        panel.add_field(
            name=category,
            value=f"{preview}\n{len(rows)} commande(s)",
            inline=True,
        )
    panel.set_footer(text="SentriX • Aide • Utilisez +help <commande> pour un accès direct")
    return panel


def _help_detail_embed(bot: commands.Bot, command: commands.Command, prefix: str) -> discord.Embed:
    slash = _slash_map(bot).get(command.qualified_name.casefold())
    title = command.qualified_name.replace("-", " ").title()
    panel = _setup_embed(f"SentriX — {title}", _command_description(command))
    panel.add_field(name="Commande", value=f"`{_command_usage(command, prefix)}`", inline=False)
    panel.add_field(name="Permission nécessaire", value=_permission_from_checks(command), inline=False)
    example = _command_usage(command, prefix).replace("[raison]", "Spam")
    panel.add_field(name="Exemple", value=f"`{example}`", inline=False)
    if slash:
        panel.add_field(name="Commande slash", value=f"`/{slash}`", inline=False)
    panel.add_field(name="Catégorie", value=_help_category(command), inline=False)
    panel.set_footer(text="SentriX • Aide commande")
    return panel


def _help_category_embed(
    bot: commands.Bot, category: str, prefix: str, page: int = 0
) -> tuple[discord.Embed, int]:
    rows = [
        command for command in _all_help_commands(bot)
        if _help_category(command) == category
    ]
    page_size = 8
    pages = max(1, (len(rows) + page_size - 1) // page_size)
    page = max(0, min(page, pages - 1))
    chunk = rows[page * page_size:(page + 1) * page_size]
    panel = _setup_embed(
        f"SentriX — {category}",
        "Commandes disponibles dans cette catégorie.",
    )
    for command in chunk:
        panel.add_field(
            name=f"{prefix}{command.qualified_name}",
            value=f"{_command_description(command)}\nPermission : {_permission_from_checks(command)}",
            inline=False,
        )
    panel.set_footer(text=f"SentriX • Aide • Page {page + 1}/{pages}")
    return panel, pages
