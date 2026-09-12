"""Définitions réelles des modules SentriX — Milestone 2 (Configuration Platform).

Chaque describe(bot, guild_id) lit UNIQUEMENT les tables déjà utilisées en
production par le module concerné (guild_config, automod_settings,
ticket_types, ai_settings, level_roles...) — aucune nouvelle table, aucun
nouvel état. install() enregistre ces définitions dans core.modules.registry ;
appelée depuis cogs/__init__.py comme n'importe quel autre installateur.

Volontairement pas exhaustif dès cette première version (pas encore Économie,
Notifications, Giveaways) : mieux vaut un petit ensemble de statuts exacts
qu'une couverture large approximative — étendre ce fichier plus tard ne
casse rien pour les modules déjà couverts.
"""
from __future__ import annotations

from .registry import ModuleDefinition, ModuleStatus, register


def _get(row, field, default=None):
    if row is None:
        return default
    try:
        value = row[field]
    except (KeyError, IndexError):
        return default
    return default if value is None else value


async def _describe_moderation(bot, guild_id: int) -> ModuleStatus:
    config = await bot.db.get_guild_config(guild_id)
    mod_role = _get(config, "mod_role")
    mute_role = _get(config, "mute_role")
    warn_role = _get(config, "warn_role")
    issues = []
    if not mod_role:
        issues.append("aucun rôle staff (mod_role) configuré")
    if not mute_role:
        issues.append("aucun rôle de mute configuré")
    configured = bool(mod_role)
    parts = []
    if mod_role:
        parts.append("rôle staff configuré")
    if mute_role:
        parts.append("rôle mute configuré")
    if warn_role:
        parts.append("rôle warn configuré")
    summary = ", ".join(parts) if parts else "aucun rôle de modération configuré"
    return ModuleStatus(enabled=True, configured=configured, summary=summary, issues=tuple(issues))


async def _describe_automod(bot, guild_id: int) -> ModuleStatus:
    row = await bot.db.get_automod(guild_id)
    filters = (
        "antispam", "antilink", "antiinvite", "antimention", "anticaps",
        "antiemoji", "antiraid", "antibot", "antiaccount", "antiscam", "antinuke",
    )
    active = [name for name in filters if _get(row, name, 0)]
    enabled = bool(active)
    summary = f"{len(active)}/{len(filters)} filtre(s) actif(s)" if enabled else "aucun filtre actif"
    return ModuleStatus(enabled=enabled, configured=enabled, summary=summary)


async def _describe_tickets(bot, guild_id: int) -> ModuleStatus:
    types_rows = await bot.db.fetchall(
        "SELECT id, staff_role_id, category_id FROM ticket_types WHERE guild_id = ?", (guild_id,)
    )
    if not types_rows:
        return ModuleStatus(enabled=False, configured=False, summary="aucun type de ticket configuré")
    missing_role = sum(1 for row in types_rows if not _get(row, "staff_role_id"))
    missing_category = sum(1 for row in types_rows if not _get(row, "category_id"))
    issues = []
    if missing_role:
        issues.append(f"{missing_role} type(s) sans rôle support")
    if missing_category:
        issues.append(f"{missing_category} type(s) sans catégorie")
    summary = f"{len(types_rows)} type(s) de ticket configuré(s)"
    return ModuleStatus(
        enabled=True, configured=not issues, summary=summary, issues=tuple(issues)
    )


async def _describe_verification(bot, guild_id: int) -> ModuleStatus:
    config = await bot.db.get_guild_config(guild_id)
    role = _get(config, "verification_role") or _get(config, "verify_role")
    channel = _get(config, "verification_channel")
    captcha = bool(_get(config, "verify_captcha_enabled", 1))
    issues = []
    if not role:
        issues.append("aucun rôle de vérification configuré")
    if not channel:
        issues.append("aucun salon de vérification configuré")
    configured = bool(role and channel)
    summary = "prêt" if configured else "configuration incomplète"
    if configured:
        summary += " (CAPTCHA actif)" if captcha else " (CAPTCHA désactivé)"
    return ModuleStatus(enabled=configured, configured=configured, summary=summary, issues=tuple(issues))


async def _describe_logs(bot, guild_id: int) -> ModuleStatus:
    config = await bot.db.get_guild_config(guild_id)
    categories = (
        "log_messages", "log_members", "log_voice", "log_roles",
        "log_server", "log_automod", "log_moderation",
    )
    active = [name for name in categories if _get(config, name)]
    has_channel = bool(_get(config, "log_channel"))
    enabled = has_channel and bool(active)
    summary = f"{len(active)}/{len(categories)} catégorie(s) configurée(s)"
    issues = () if has_channel else ("aucun salon de logs configuré",)
    return ModuleStatus(enabled=enabled, configured=enabled, summary=summary, issues=issues)


async def _describe_welcome(bot, guild_id: int) -> ModuleStatus:
    config = await bot.db.get_guild_config(guild_id)
    channel = _get(config, "welcome_channel")
    message = _get(config, "welcome_message")
    configured = bool(channel and message)
    summary = "configuré" if configured else "non configuré"
    issues = () if configured else ("aucun salon ou message de bienvenue configuré",)
    return ModuleStatus(enabled=bool(channel), configured=configured, summary=summary, issues=issues)


async def _describe_levels(bot, guild_id: int) -> ModuleStatus:
    rewards = await bot.db.fetchall(
        "SELECT level, role_id FROM level_roles WHERE guild_id = ?", (guild_id,)
    )
    config = await bot.db.get_guild_config(guild_id)
    multiplier = _get(config, "xp_multiplier", 1.0)
    summary = f"{len(rewards)} rôle(s) de récompense" if rewards else "aucun rôle de récompense"
    if multiplier and float(multiplier) != 1.0:
        summary += f", multiplicateur x{multiplier}"
    return ModuleStatus(enabled=True, configured=bool(rewards), summary=summary)


async def _describe_ai(bot, guild_id: int) -> ModuleStatus:
    row = await bot.db.fetchone("SELECT * FROM ai_settings WHERE guild_id = ?", (guild_id,))
    if row is None:
        return ModuleStatus(enabled=True, configured=False, summary="réglages par défaut (jamais modifiés)")
    enabled = bool(_get(row, "enabled", 1))
    model = _get(row, "default_model", "terra")
    summary = f"actif (modèle {model})" if enabled else "désactivé"
    return ModuleStatus(enabled=enabled, configured=True, summary=summary)


def install() -> None:
    register(ModuleDefinition(
        key="moderation", label="Modération", describe=_describe_moderation,
        commands=("ban", "kick", "mute", "warn", "unban"), dashboard_page="moderation",
    ))
    register(ModuleDefinition(
        key="automod", label="AutoMod", describe=_describe_automod,
        commands=("automod-status", "automod-history"), dashboard_page="automod",
    ))
    register(ModuleDefinition(
        key="tickets", label="Tickets", describe=_describe_tickets,
        commands=("ticket",), dashboard_page="tickets",
    ))
    register(ModuleDefinition(
        key="verification", label="Vérification", describe=_describe_verification,
        dashboard_page="verification",
    ))
    register(ModuleDefinition(
        key="logs", label="Logs", describe=_describe_logs, dashboard_page="logs",
    ))
    register(ModuleDefinition(
        key="welcome", label="Bienvenue", describe=_describe_welcome, dashboard_page="welcome",
    ))
    register(ModuleDefinition(
        key="levels", label="Niveaux", describe=_describe_levels,
        commands=("level", "leaderboard"), dashboard_page="levels",
    ))
    register(ModuleDefinition(
        key="ai", label="Intelligence artificielle", describe=_describe_ai,
        commands=("ask", "chat"), dashboard_page="ai",
    ))
